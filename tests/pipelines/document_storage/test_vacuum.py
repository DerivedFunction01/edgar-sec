"""Cross-run snapshot consolidation: the correctness oracle for vacuuming.

Covers union materialization, dependency-aware purge, source precedence, quarter
repartitioning, conflict refusal, byte-budgeted parts, and source immutability —
the cases a consolidation can only be trusted on if they are stated.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edgar_sec.domain.document.models import DocumentLocator, FilingOccurrence
from edgar_sec.domain.identity import Cik
from edgar_sec.infra.storage.document_parquet import write_chunk_snapshot
from edgar_sec.infra.storage.document_parts import (
    PartError,
    plan_parts,
    relation_for_parts,
    validate_part_paths,
)
from edgar_sec.infra.storage.manifests import (
    ManifestError,
    SnapshotPart,
    expand_dependency_closure,
    list_snapshots,
    read_pointer,
)
from edgar_sec.pipelines.document_storage.merger import publish_snapshot
from edgar_sec.pipelines.document_storage.paths import chunk_checkpoint_path
from edgar_sec.pipelines.document_storage.queries import (
    effective_snapshot_relations,
    query_sql_batches,
    ranked_union_relations,
)
from edgar_sec.pipelines.document_storage.vacuum import (
    VacuumError,
    vacuum_snapshots,
)

ACCESSION = "0001234567-11-000001"


def _chunk(
    chunks_dir: Path,
    chunk_id: str,
    rows: list[tuple[str, str, str, str]],
) -> None:
    """Write a chunk checkpoint: (document_path, form, filing_date, text)."""
    occurrences = []
    raw = {}
    texts = {}
    statuses = {}
    for document_path, form, filing_date, text in rows:
        locator = DocumentLocator.from_parts(ACCESSION, document_path)
        occurrence = FilingOccurrence(
            occurrence_id=f"occ-{locator.document_locator_key[:10]}",
            source_cik=Cik.from_raw("1234567"),
            accession=locator.accession,
            document_path=document_path,
            form=form,
            filing_date=filing_date,
            report_date=None,
            doc_id=locator.document_locator_key,
        )
        occurrences.append(occurrence)
        raw[locator.document_locator_key] = text.encode()
        texts[occurrence.occurrence_id] = text
        statuses[occurrence.occurrence_id] = "ok"
    write_chunk_snapshot(
        chunk_checkpoint_path(chunks_dir, chunk_id),
        occurrences,
        raw,
        texts,
        statuses,
        {},
    )


def _publish(root: Path, run_id: str, rows: list[tuple[str, str, str, str]]) -> dict:
    chunks_dir = root / "runs" / run_id / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    _chunk(chunks_dir, "c1", rows)
    return publish_snapshot(run_id=run_id, chunks_dir=chunks_dir, snapshots_root=root)


def _manifest(root: Path, snapshot_id: str) -> dict:
    pointer = read_pointer(root)
    assert pointer is not None
    for manifest in list_snapshots(root):
        if manifest["snapshot_id"] == snapshot_id:
            return manifest
    raise AssertionError(f"snapshot {snapshot_id} not published")


def _consolidated_rows(root: Path, snapshot_id: str) -> list[dict]:
    """Read a consolidated snapshot's index rows back, ordered by document.

    Reads the stored part directly, so it reports what was actually written.
    ``filing_year``/``filing_quarter`` are absent by design: they are derived at
    read time, not stored, so :func:`_derived_quarters` covers them instead.
    """
    from edgar_sec.infra.storage.manifests import SnapshotReader, snapshot_dir

    reader = SnapshotReader(root, snapshot_id)
    parts = reader.parts("index")
    connection = _connect()
    try:
        query = (
            "SELECT occurrence_id, document_path, doc_id, form, filing_date, "
            f"payload_file FROM {relation_for_parts(parts, snapshot_dir(root, snapshot_id))} "
            "ORDER BY doc_id"
        )
        return [row for batch in query_sql_batches(connection, query) for row in batch]
    finally:
        connection.close()


def _derived_quarters(root: Path, snapshot_id: str) -> list[tuple[int, str]]:
    """Derive fiscal quarters the way a consumer does, from the effective relation."""
    from edgar_sec.infra.storage.manifests import SnapshotReader, snapshot_dir
    from edgar_sec.pipelines.document_storage.vacuum import effective_relations

    reader = SnapshotReader(root, snapshot_id)
    _index, _payload = effective_relations(root, [reader.manifest])
    connection = _connect()
    try:
        return [
            (int(row["filing_year"]), str(row["filing_quarter"]))
            for batch in query_sql_batches(
                connection,
                f"SELECT DISTINCT filing_year, filing_quarter "
                f"FROM ({_index}) ORDER BY filing_year, filing_quarter",
            )
            for row in batch
        ]
    finally:
        connection.close()
    _ = snapshot_dir


def _connect():
    from edgar_sec.infra.storage.duckdb import connect

    return connect()


# --- part planning --------------------------------------------------------


def test_parts_split_by_byte_budget_not_row_count() -> None:
    """An oversized document gets its own part rather than blowing the budget."""
    planned = plan_parts(
        [("a", 10), ("b", 10), ("c", 5_000)],
        year=2011,
        quarter="QTR1",
        target_bytes=100,
        kind="payload",
    )
    assert [part.doc_ids for part in planned] == [("a", "b"), ("c",)]
    assert planned[0].estimated_bytes == 20


def test_a_single_oversized_document_still_becomes_a_part() -> None:
    planned = plan_parts(
        [("a", 10_000)],
        year=2011,
        quarter="QTR1",
        target_bytes=100,
        kind="payload",
    )
    assert len(planned) == 1
    assert planned[0].estimated_bytes == 10_000


def test_no_documents_plans_nothing() -> None:
    assert (
        plan_parts(
            [],
            year=2011,
            quarter="QTR1",
            target_bytes=100,
            kind="payload",
        )
        == []
    )


def test_a_non_positive_budget_is_rejected() -> None:
    with pytest.raises(PartError):
        plan_parts(
            [("a", 1)],
            year=2011,
            quarter="QTR1",
            target_bytes=0,
            kind="payload",
        )


def test_relation_over_zero_parts_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(PartError):
        relation_for_parts([], tmp_path)


def test_unsafe_part_paths_are_rejected(tmp_path: Path) -> None:
    for path in ("../escape.parquet", "/abs.parquet", "a'b.parquet", "a;b.parquet"):
        with pytest.raises(PartError):
            validate_part_paths([SnapshotPart(path=path, kind="index")], tmp_path)


def test_a_missing_part_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(PartError, match="missing"):
        validate_part_paths([SnapshotPart(path="nope.parquet", kind="index")], tmp_path)


def test_a_quoted_path_in_a_manifest_cannot_reach_sql(tmp_path: Path) -> None:
    """A hand-edited manifest must not be able to rewrite a statement."""
    hostile = SnapshotPart(path="x'; DROP TABLE y; --.parquet", kind="index")
    with pytest.raises(PartError):
        validate_part_paths([hostile], tmp_path)
    # Escaping still applies to a path that passes validation, so a legal path
    # carrying a quote cannot terminate the string literal.
    assert "''" in relation_for_parts(
        [SnapshotPart(path="a'b.parquet", kind="index")], tmp_path
    )


# --- consolidation --------------------------------------------------------


def test_consolidation_materializes_the_union(tmp_path: Path) -> None:
    """Two runs become one snapshot."""
    first = _publish(tmp_path, "run-1", [("a.htm", "10-K", "2011-02-15", "one")])
    second = _publish(tmp_path, "run-2", [("b.htm", "10-K", "2011-08-15", "two")])

    manifest = vacuum_snapshots(
        snapshots_root=tmp_path,
        snapshot_ids=[first.snapshot.snapshot_id, second.snapshot.snapshot_id],
        workers=2,
        target_bytes=1024,
    )
    rows = _consolidated_rows(tmp_path, manifest["snapshot_id"])
    assert len(rows) == 2
    assert {row["document_path"] for row in rows} == {"a.htm", "b.htm"}
    assert manifest["merged_from"] == sorted(
        [first.snapshot.snapshot_id, second.snapshot.snapshot_id]
    )


def test_consolidation_repartitions_into_fiscal_quarters(tmp_path: Path) -> None:
    first = _publish(tmp_path, "run-1", [("a.htm", "10-K", "2011-02-15", "one")])
    second = _publish(tmp_path, "run-2", [("b.htm", "10-K", "2011-08-15", "two")])
    manifest = vacuum_snapshots(
        snapshots_root=tmp_path,
        snapshot_ids=[first.snapshot.snapshot_id, second.snapshot.snapshot_id],
        target_bytes=1024,
    )
    quarters = _derived_quarters(tmp_path, manifest["snapshot_id"])
    assert (2011, "QTR1") in quarters
    assert (2011, "QTR3") in quarters


def test_consolidation_records_where_each_payload_lives(tmp_path: Path) -> None:
    first = _publish(tmp_path, "run-1", [("a.htm", "10-K", "2011-02-15", "one")])
    manifest = vacuum_snapshots(
        snapshots_root=tmp_path,
        snapshot_ids=[first.snapshot.snapshot_id],
        target_bytes=1024,
    )
    row = _consolidated_rows(tmp_path, manifest["snapshot_id"])[0]
    assert row["payload_file"]
    assert row["payload_file"].endswith(".parquet")


def test_consolidation_preserves_the_form(tmp_path: Path) -> None:
    first = _publish(tmp_path, "run-1", [("a.htm", "10-Q", "2011-05-15", "one")])
    manifest = vacuum_snapshots(
        snapshots_root=tmp_path,
        snapshot_ids=[first.snapshot.snapshot_id],
        target_bytes=1024,
    )
    assert _consolidated_rows(tmp_path, manifest["snapshot_id"])[0]["form"] == "10-Q"


def test_one_document_survives_consolidating_the_same_document_twice(
    tmp_path: Path,
) -> None:
    """The same document in two sources collapses to one row, not two.

    Text must agree for this to consolidate at all: differing text is refused
    outright, so precedence is only reachable for a document whose payload the
    two sources agree on and whose index rows may differ.
    """
    first = _publish(tmp_path, "run-1", [("a.htm", "10-K", "2011-02-15", "one")])
    second = _publish(tmp_path, "run-2", [("a.htm", "10-K", "2011-02-15", "one")])
    manifest = vacuum_snapshots(
        snapshots_root=tmp_path,
        snapshot_ids=[first.snapshot.snapshot_id, second.snapshot.snapshot_id],
        target_bytes=1024,
    )
    assert len(_consolidated_rows(tmp_path, manifest["snapshot_id"])) == 1


def test_the_derived_snapshot_id_does_not_depend_on_list_order(
    tmp_path: Path,
) -> None:
    """A snapshot id identifies content, so the same sources give the same id.

    Order still decides *precedence* inside the union (see
    ``test_ranked_union_encodes_precedence``); it deliberately does not decide the
    snapshot's identity, because a consumer that consolidated the same two runs in
    a different order got the same result and should be recognised as a no-op.
    """
    first = _publish(tmp_path, "run-1", [("a.htm", "10-K", "2011-02-15", "one")])
    second = _publish(tmp_path, "run-2", [("a.htm", "10-K", "2011-02-15", "one")])
    forward = vacuum_snapshots(
        snapshots_root=tmp_path,
        snapshot_ids=[first.snapshot.snapshot_id, second.snapshot.snapshot_id],
        target_bytes=1024,
    )
    other = tmp_path.parent / f"{tmp_path.name}-reordered"
    first = _publish(other, "run-1", [("a.htm", "10-K", "2011-02-15", "one")])
    second = _publish(other, "run-2", [("a.htm", "10-K", "2011-02-15", "one")])
    backward = vacuum_snapshots(
        snapshots_root=other,
        snapshot_ids=[second.snapshot.snapshot_id, first.snapshot.snapshot_id],
        target_bytes=1024,
    )
    assert forward["snapshot_id"] == backward["snapshot_id"]


def test_conflicting_text_is_refused(tmp_path: Path) -> None:
    """Two sources with different text for one document is a refusal, not a choice."""
    # Same doc_id in both sources, different text: the conflict a precedence rule
    # would otherwise silently resolve.
    _write_raw_snapshot(tmp_path, "snap-a", {"a.htm": "one"}, doc_prefix="shared")
    _write_raw_snapshot(tmp_path, "snap-b", {"a.htm": "DIFFERENT"}, doc_prefix="shared")
    with pytest.raises(VacuumError, match="conflicting normalized content"):
        vacuum_snapshots(
            snapshots_root=tmp_path,
            snapshot_ids=["snap-a", "snap-b"],
            target_bytes=1024,
        )


def test_identical_text_across_sources_is_not_a_conflict(tmp_path: Path) -> None:
    _write_raw_snapshot(tmp_path, "snap-a", {"a.htm": "one"}, doc_prefix="shared")
    _write_raw_snapshot(
        tmp_path, "snap-b", {"a.htm": "one", "b.htm": "two"}, doc_prefix="shared"
    )
    manifest = vacuum_snapshots(
        snapshots_root=tmp_path, snapshot_ids=["snap-a", "snap-b"], target_bytes=1024
    )
    assert len(_consolidated_rows(tmp_path, manifest["snapshot_id"])) == 2


def _write_raw_snapshot(
    root: Path,
    snapshot_id: str,
    documents: dict[str, str],
    *,
    doc_prefix: str | None = None,
    filing_dates: dict[str, str] | None = None,
) -> None:
    """Publish a snapshot directly from a document/text map."""
    from edgar_sec.infra.storage.document_parts import (
        PlannedPart,
        write_index_part,
        write_payload_part,
    )
    from edgar_sec.infra.storage.manifests import write_manifest

    target = root / snapshot_id
    index_rows = []
    payloads = []
    for index, (document_path, text) in enumerate(sorted(documents.items())):
        doc_id = f"{doc_prefix or snapshot_id}-{index:04d}"
        payloads.append((doc_id, text))
        index_rows.append(
            {
                "occurrence_id": f"occ-{index}",
                "source_cik": "1234567",
                "accession": ACCESSION,
                "form": "10-K",
                "filing_date": (
                    filing_dates.get(document_path, "2011-02-15")
                    if filing_dates is not None
                    else "2011-02-15"
                ),
                "report_date": None,
                "document_path": document_path,
                "doc_id": doc_id,
                "mime_type": "text/plain",
                "byte_size": str(len(text)),
                "payload_file": "",
            }
        )
    doc_ids = tuple(row["doc_id"] for row in index_rows)
    payload_part = PlannedPart(
        path="parts/payload/run.parquet",
        kind="payload",
        doc_ids=doc_ids,
        estimated_bytes=sum(len(text) for text in documents.values()),
    )
    index_part = PlannedPart(
        path="parts/index/run.parquet",
        kind="index",
        doc_ids=doc_ids,
        estimated_bytes=0,
    )
    for row in index_rows:
        row["payload_file"] = payload_part.path
    write_payload_part(target, payload_part, payloads)
    parts = [
        write_index_part(target, index_part, index_rows).to_dict(),
        write_payload_part(target, payload_part, payloads).to_dict(),
    ]
    write_manifest(
        root,
        {
            "snapshot_id": snapshot_id,
            "schema_version": "1",
            "resolved_parts": parts,
            "source_snapshot_ids": [snapshot_id],
            "dataset": "document_storage",
            "phase": "025_webpage_storage",
            "logical_fingerprint": snapshot_id,
        },
        set_current=False,
    )


def test_consolidation_requires_sources(tmp_path: Path) -> None:
    with pytest.raises(VacuumError, match="requires"):
        vacuum_snapshots(snapshots_root=tmp_path, snapshot_ids=[])


def test_consolidation_rejects_an_unknown_snapshot(tmp_path: Path) -> None:
    with pytest.raises(ManifestError):
        vacuum_snapshots(snapshots_root=tmp_path, snapshot_ids=["nope"])


def test_consolidating_everything(tmp_path: Path) -> None:
    _write_raw_snapshot(tmp_path, "snap-a", {"a.htm": "one"})
    _write_raw_snapshot(tmp_path, "snap-b", {"b.htm": "two"})
    manifest = vacuum_snapshots(
        snapshots_root=tmp_path, include_all=True, target_bytes=1024
    )
    assert manifest["merged_from"] == ["snap-a", "snap-b"]


def test_a_repeat_consolidation_is_refused(tmp_path: Path) -> None:
    """Snapshots are immutable, so re-consolidating the same sources is a no-op."""
    _write_raw_snapshot(tmp_path, "snap-a", {"a.htm": "one"})
    _write_raw_snapshot(tmp_path, "snap-b", {"b.htm": "two"})
    first = vacuum_snapshots(
        snapshots_root=tmp_path, snapshot_ids=["snap-a", "snap-b"], target_bytes=1024
    )
    with pytest.raises(VacuumError, match="already exists"):
        vacuum_snapshots(
            snapshots_root=tmp_path,
            snapshot_ids=["snap-a", "snap-b"],
            target_bytes=1024,
        )
    _ = first


def test_consolidation_id_is_deterministic(tmp_path: Path) -> None:
    def _identity() -> str:
        _write_raw_snapshot(tmp_path, "snap-a", {"a.htm": "one"})
        _write_raw_snapshot(tmp_path, "snap-b", {"b.htm": "two"})
        return vacuum_snapshots(
            snapshots_root=tmp_path,
            snapshot_ids=["snap-a", "snap-b"],
            target_bytes=1024,
        )["snapshot_id"]

    first = _identity()
    shutil_root = tmp_path.parent / f"{tmp_path.name}-second"
    _write_raw_snapshot(shutil_root, "snap-a", {"a.htm": "one"})
    _write_raw_snapshot(shutil_root, "snap-b", {"b.htm": "two"})
    second = vacuum_snapshots(
        snapshots_root=shutil_root, snapshot_ids=["snap-a", "snap-b"], target_bytes=1024
    )["snapshot_id"]
    assert first == second


def test_consolidation_points_current_at_the_result(tmp_path: Path) -> None:
    _write_raw_snapshot(tmp_path, "snap-a", {"a.htm": "one"})
    _write_raw_snapshot(tmp_path, "snap-b", {"b.htm": "two"})
    manifest = vacuum_snapshots(
        snapshots_root=tmp_path, snapshot_ids=["snap-a", "snap-b"], target_bytes=1024
    )
    pointer = read_pointer(tmp_path)
    assert pointer is not None
    assert pointer["snapshot_id"] == manifest["snapshot_id"]


def test_consolidation_emits_progress(tmp_path: Path) -> None:
    _write_raw_snapshot(tmp_path, "snap-a", {"a.htm": "one"})
    events: list[str] = []
    vacuum_snapshots(
        snapshots_root=tmp_path,
        snapshot_ids=["snap-a"],
        target_bytes=1024,
        progress=lambda event: events.append(str(event["type"])),
    )
    assert "sources_resolved" in events
    assert "quarter_done" in events
    assert "publish_manifest" in events


def test_consolidation_writes_a_manifest_json(tmp_path: Path) -> None:
    _write_raw_snapshot(tmp_path, "snap-a", {"a.htm": "one"})
    manifest = vacuum_snapshots(
        snapshots_root=tmp_path, snapshot_ids=["snap-a"], target_bytes=1024
    )
    written = _manifest(tmp_path, manifest["snapshot_id"])
    assert written["provenance"]["operation"] == "vacuum"
    assert json.dumps(written)


# --- source immutability and purge ---------------------------------------


def test_consolidation_does_not_modify_its_sources(tmp_path: Path) -> None:
    _write_raw_snapshot(tmp_path, "snap-a", {"a.htm": "one"})
    _write_raw_snapshot(tmp_path, "snap-b", {"b.htm": "two"})
    before = {
        manifest["snapshot_id"]: json.dumps(manifest, sort_keys=True)
        for manifest in list_snapshots(tmp_path)
    }
    vacuum_snapshots(
        snapshots_root=tmp_path, snapshot_ids=["snap-a", "snap-b"], target_bytes=1024
    )
    after = {
        manifest["snapshot_id"]: json.dumps(manifest, sort_keys=True)
        for manifest in list_snapshots(tmp_path)
    }
    for snapshot_id, text in before.items():
        assert after[snapshot_id] == text


def test_purge_requires_a_dependency_closure(tmp_path: Path) -> None:
    """A source whose parts a retained snapshot uses cannot go."""
    _write_raw_snapshot(tmp_path, "snap-a", {"a.htm": "one"})
    shared = "snap-shared"
    _write_shared_snapshot(tmp_path, shared, {"a.htm": "one"})

    with pytest.raises(VacuumError, match="referenced"):
        vacuum_snapshots(
            snapshots_root=tmp_path,
            snapshot_ids=["snap-a"],
            target_bytes=1024,
            purge_sources=True,
        )

    manifest = vacuum_snapshots(
        snapshots_root=tmp_path,
        snapshot_ids=["snap-a"],
        target_bytes=1024,
        purge_dependency_closure=True,
    )
    assert set(manifest["merged_from"]) == {"snap-a", shared}


def test_purge_removes_the_sources(tmp_path: Path) -> None:
    _write_raw_snapshot(tmp_path, "snap-a", {"a.htm": "one"})
    vacuum_snapshots(
        snapshots_root=tmp_path,
        snapshot_ids=["snap-a"],
        target_bytes=1024,
        purge_sources=True,
    )
    remaining = [m["snapshot_id"] for m in list_snapshots(tmp_path)]
    assert "snap-a" not in remaining
    assert len(remaining) == 1


def test_purge_keeps_a_snapshot_that_survives(tmp_path: Path) -> None:
    _write_raw_snapshot(tmp_path, "snap-a", {"a.htm": "one"})
    manifest = vacuum_snapshots(
        snapshots_root=tmp_path,
        snapshot_ids=["snap-a"],
        target_bytes=1024,
        purge_sources=True,
    )
    assert manifest["snapshot_id"] in [
        m["snapshot_id"] for m in list_snapshots(tmp_path)
    ]


def test_dependency_closure_grows_to_its_fixpoint(tmp_path: Path) -> None:
    _write_raw_snapshot(tmp_path, "snap-a", {"a.htm": "one"})
    _write_shared_snapshot(tmp_path, "snap-b", {"a.htm": "one"})
    _write_shared_snapshot(tmp_path, "snap-c", {"a.htm": "one"})
    closure = expand_dependency_closure(tmp_path, {"snap-a"})
    assert closure >= {"snap-a", "snap-b", "snap-c"}


def _write_shared_snapshot(
    root: Path, snapshot_id: str, documents: dict[str, str]
) -> None:
    """Publish a snapshot that reuses another snapshot's part paths."""
    from edgar_sec.infra.storage.manifests import write_manifest

    source = [m for m in list_snapshots(root) if m["snapshot_id"] == "snap-a"]
    assert source, "snap-a must exist first"
    # A dependent snapshot whose parts live in its own directory but carry the
    # same doc ids and content: the case purge must refuse.
    parts = [dict(row) for row in source[0]["resolved_parts"]]
    for part in parts:
        original = root / "snap-a" / part["path"]
        target = root / snapshot_id / part["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(original.read_bytes())
    write_manifest(
        root,
        {
            "snapshot_id": snapshot_id,
            "schema_version": "1",
            "resolved_parts": parts,
            "source_snapshot_ids": [snapshot_id],
            "dataset": "document_storage",
            "phase": "025_webpage_storage",
            "logical_fingerprint": snapshot_id,
        },
        set_current=False,
    )
    _ = documents


# --- relation helpers -----------------------------------------------------


def test_ranked_union_encodes_precedence() -> None:
    relation = ranked_union_relations(["A", "B", "C"])
    assert "0 AS _snapshot_rank" in relation
    assert "2 AS _snapshot_rank" in relation
    assert relation.count("UNION ALL") == 2


def test_ranked_union_requires_a_relation() -> None:
    with pytest.raises(ValueError, match="at least one"):
        ranked_union_relations([])


def test_effective_relations_dedupe_by_precedence() -> None:
    index, payload = effective_snapshot_relations("IDX", "PAY")
    assert "ROW_NUMBER() OVER" in index
    assert "ORDER BY _snapshot_rank DESC" in index
    assert "PARTITION BY doc_id" in payload


def test_batch_reading_is_bounded() -> None:
    connection = _connect()
    try:
        batches = list(
            query_sql_batches(connection, "SELECT * FROM range(5)", batch_size=2)
        )
        assert [len(batch) for batch in batches] == [2, 2, 1]
    finally:
        connection.close()


def test_a_non_positive_batch_size_is_rejected() -> None:
    connection = _connect()
    try:
        with pytest.raises(ValueError, match="batch_size"):
            list(query_sql_batches(connection, "SELECT 1", batch_size=0))
    finally:
        connection.close()


def test_an_undated_document_is_bucketed_not_dropped(tmp_path: Path) -> None:
    """A missing filing_date must not abort a consolidation, nor lose a document.

    ``CAST(substr('', 1, 4) AS INTEGER)`` raises, which would fail the whole
    consolidation over one malformed row. Undated documents belong in an explicit
    ``QTR0`` bucket: reportable, and visible to a reviewer.
    """
    _write_raw_snapshot(
        tmp_path,
        "snap-a",
        {"dated.htm": "one", "undated.htm": "two"},
        filing_dates=None,
    )
    manifest = vacuum_snapshots(
        snapshots_root=tmp_path, snapshot_ids=["snap-a"], target_bytes=1024
    )
    rows = _consolidated_rows(tmp_path, manifest["snapshot_id"])
    assert {row["document_path"] for row in rows} == {"dated.htm", "undated.htm"}


def test_an_undated_document_lands_in_qtr0(tmp_path: Path) -> None:
    _write_raw_snapshot(
        tmp_path, "snap-a", {"undated.htm": "two"}, filing_dates={"undated.htm": ""}
    )
    manifest = vacuum_snapshots(
        snapshots_root=tmp_path, snapshot_ids=["snap-a"], target_bytes=1024
    )
    assert _derived_quarters(tmp_path, manifest["snapshot_id"]) == [(0, "QTR0")]


@pytest.mark.parametrize(
    ("filing_date", "expected"),
    [
        # A readable year with an unusable month keeps its year.
        ("2011-13-15", (2011, "QTR0")),
        # A truncated date has no month either, but the year still parses.
        ("2011", (2011, "QTR0")),
        # An empty date has no usable year at all.
        ("", (0, "QTR0")),
    ],
)
def test_a_degenerate_date_lands_in_qtr0_without_losing_its_year(
    tmp_path: Path, filing_date: str, expected: tuple[int, str]
) -> None:
    _write_raw_snapshot(
        tmp_path, "snap-a", {"odd.htm": "one"}, filing_dates={"odd.htm": filing_date}
    )
    manifest = vacuum_snapshots(
        snapshots_root=tmp_path, snapshot_ids=["snap-a"], target_bytes=1024
    )
    assert _derived_quarters(tmp_path, manifest["snapshot_id"]) == [expected]
    assert len(_consolidated_rows(tmp_path, manifest["snapshot_id"])) == 1
