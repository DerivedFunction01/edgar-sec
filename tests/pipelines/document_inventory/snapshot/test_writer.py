from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from edgar_sec.domain.document_inventory.models import (
    IndexWorkItem,
    InventoryEntry,
    ParsedIndexPage,
    ParserDiagnostics,
)
from edgar_sec.domain.document_inventory.schemas import ENTRY_SCHEMA
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.dag import publication as publication_module
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.pipelines.document_inventory.checkpoint import (
    AttemptWriters,
    entry_rows,
    finalize_attempt,
    new_attempt_id,
    outcome_row,
)
from edgar_sec.pipelines.document_inventory.paths import (
    InventoryPaths,
    inventory_run_paths,
)
from edgar_sec.pipelines.document_inventory.run_manifest import (
    iter_work_order_chunks,
    write_run_manifest,
    write_work_order,
)
from edgar_sec.pipelines.document_inventory.snapshot.errors import (
    ValidationFailedError,
)
from edgar_sec.infra.storage.dag.publication import (
    PublicationLock,
    PublicationLockError,
    StaleParentError,
)
from edgar_sec.pipelines.document_inventory.snapshot.reader import (
    get_active_entries,
)
from edgar_sec.pipelines.document_inventory.snapshot.schema import (
    SNAPSHOT_ACCESSION_SOURCES_SCHEMA,
    SNAPSHOT_ACCESSIONS_SCHEMA,
)
from edgar_sec.pipelines.document_inventory.snapshot.validation import validate_snapshot
from edgar_sec.pipelines.document_inventory.snapshot.writer import (
    publish_committed_chunks,
)

_COHORT_ACCESSIONS_SCHEMA = pa.schema(
    [
        ("accession", pa.string()),
        ("filing_cik", pa.string()),
        ("form", pa.string()),
        ("filing_date", pa.string()),
        ("report_date", pa.string()),
        ("index_url", pa.string()),
    ]
)


def _url(accession: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{accession}-index.html"


def _parsed(item: IndexWorkItem, revision: str = "") -> ParsedIndexPage:
    accession = item.accession
    digest = hashlib.sha256(f"{accession}{revision}".encode()).hexdigest()
    return ParsedIndexPage(
        accession=accession,
        source_url=item.index_url,
        page_sha256=digest,
        entries=(
            InventoryEntry(
                entry_id=f"entry-{accession}-{digest[:8]}",
                accession=accession,
                table_kind="document_format",
                row_ordinal=0,
                sequence=1,
                document_type="10-K",
                document_label="Annual report",
                description="Annual report filing",
                filename="report.htm",
                href="report.htm",
                archive_url=f"https://www.sec.gov/Archives/{accession}/report.htm",
                byte_size=17,
            ),
        ),
        bundle_url=None,
        bundle_size=None,
        xbrl_candidate_url=None,
        diagnostics=ParserDiagnostics((), 0),
    )


def _prepare_run(
    root: Path,
    run_id: str,
    items: list[IndexWorkItem],
    accession_facts: list[dict],
    source_facts: list[dict],
    *,
    parent_id: str | None = None,
    status: str = "parsed",
    refresh_mode: str = "normal",
    page_revision: str = "",
):
    paths = inventory_run_paths(root, run_id)
    work_order = paths.work_order_path()
    write_work_order(work_order, items)
    run = write_run_manifest(
        paths,
        parent_snapshot_id=parent_id or "",
        canonical_cohort_id=f"cohort-{run_id}",
        source_identity=f"source-{run_id}",
        parser_version="parser-test",
        chunk_size=2,
        refresh_mode=refresh_mode,
        fetch_mode="live",
        work_order_path=work_order,
    )
    for chunk, members in iter_work_order_chunks(
        work_order,
        chunk_size=run.chunk_size,
        work_order_version=run.work_order_version,
    ):
        attempt_id = new_attempt_id()
        writers = AttemptWriters(paths, chunk.chunk_id, attempt_id)
        for member in members:
            if status == "parsed":
                result = _parsed(member, page_revision)
                outcome = outcome_row(result, index_url=member.index_url)
                entries = entry_rows(result)
            else:
                outcome = {
                    "accession": str(member.accession),
                    "status": status,
                    "index_url": member.index_url,
                    "page_sha256": None,
                    "response_size": None,
                    "entry_count": 0,
                    "xbrl_candidate_url": None,
                    "bundle_url": None,
                    "bundle_size": None,
                    "diagnostics_json": "",
                    "error_code": status,
                    "error_detail": "synthetic refusal",
                }
                entries = []
            writers.add(outcome, entries)
        writers.close()
        finalize_attempt(
            paths,
            chunk.chunk_id,
            attempt_id,
            membership=tuple(str(member.accession) for member in members),
            run=run,
        )
    pq.write_table(
        pa.Table.from_pylist(accession_facts, schema=_COHORT_ACCESSIONS_SCHEMA),
        paths.cohort_accessions_path(),
    )
    pq.write_table(
        pa.Table.from_pylist(source_facts, schema=SNAPSHOT_ACCESSION_SOURCES_SCHEMA),
        paths.cohort_sources_path(),
    )
    return paths, run


def _fact(accession: str, *, date: str = "2025-03-04") -> dict:
    return {
        "accession": accession,
        "filing_cik": accession[:10],
        "form": "10-K",
        "filing_date": date,
        "report_date": "2024-12-31",
        "index_url": _url(accession),
    }


def _source(accession: str, cik: str) -> dict:
    return {
        "accession": accession,
        "source_cik": cik,
        "first_seen_by": "catalog-test",
    }


def _publish(
    root: Path,
    run_id: str,
    accessions: list[str],
    source_rows: list[dict],
    *,
    dates: dict[str, str] | None = None,
    parent_id: str | None = None,
):
    items = [IndexWorkItem(AccessionNumber(value), _url(value)) for value in accessions]
    facts = [
        _fact(value, date=(dates or {}).get(value, "2025-03-04"))
        for value in accessions
    ]
    paths, run = _prepare_run(
        root, run_id, items, facts, source_rows, parent_id=parent_id
    )
    result = publish_committed_chunks(
        paths,
        run,
        cohort_accessions_path=paths.cohort_accessions_path(),
        cohort_sources_path=paths.cohort_sources_path(),
        expected_parent_snapshot_id=parent_id,
    )
    return paths, run, result


def test_publisher_merges_validated_chunks_and_inherits_unchanged_parts(
    tmp_path: Path,
) -> None:
    first_accession = "0000000001-25-000001"
    second_accession = "0000000002-26-000002"
    paths, _run, first = _publish(
        tmp_path,
        "first-run",
        [first_accession],
        [_source(first_accession, "0000000099")],
        dates={first_accession: "2025-03-04"},
    )
    assert first.status == "published"
    assert first.snapshot is not None
    catalog = DAGCatalog(InventoryPaths(tmp_path).snapshots_root)
    pointer = catalog.read_pointer()
    assert pointer is not None
    assert pointer["snapshot_id"] == first.snapshot.snapshot_id
    assert pointer["manifest_sha256"] == catalog.get_manifest_sha256(
        first.snapshot.snapshot_id
    )

    child_paths, _run, second = _publish(
        tmp_path,
        "second-run",
        [second_accession],
        [
            _source(first_accession, "0000000099"),
            _source(first_accession, "0000000088"),
            _source(second_accession, "0000000088"),
        ],
        dates={first_accession: "2025-03-04", second_accession: "2026-02-05"},
        parent_id=first.snapshot.snapshot_id,
    )

    assert second.status == "published"
    assert second.snapshot is not None
    assert second.snapshot.accession_count == 1
    assert second.snapshot.entry_count == 1
    assert second.snapshot.source_cik_count == 2
    assert len(second.snapshot.accessions_partitions) == 1
    assert second.snapshot.accessions_partitions[0].key_min == second_accession
    assert any(
        part.path.endswith("part-00000.parquet")
        for part in second.snapshot.accession_sources_partitions
    )
    manifest = catalog.get_manifest(second.snapshot.snapshot_id)
    assert manifest is not None
    assert manifest.kind == "delta"
    assert manifest.lineage_depth == 1
    assert manifest.checkpoint_anchor_id == first.snapshot.snapshot_id
    assert "accessions" in manifest.relations
    assert len(manifest.relations["accessions"]) == 1
    checked = validate_snapshot(InventoryPaths(tmp_path), second.snapshot.snapshot_id)
    assert checked.accession_count == 1
    assert pq.read_schema(
        InventoryPaths(tmp_path).snapshot_root(second.snapshot.snapshot_id)
        / "accessions/part-00000.parquet"
    ).equals(SNAPSHOT_ACCESSIONS_SCHEMA, check_metadata=False)
    assert pq.read_schema(
        InventoryPaths(tmp_path).snapshot_root(second.snapshot.snapshot_id)
        / "entries/part-00000.parquet"
    ).equals(ENTRY_SCHEMA, check_metadata=False)


def test_refusal_does_not_publish_and_partial_progress_is_not_an_input(
    tmp_path: Path,
) -> None:
    accession = "0000000001-25-000001"
    paths, run = _prepare_run(
        tmp_path,
        "refusal-run",
        [IndexWorkItem(AccessionNumber(accession), _url(accession))],
        [_fact(accession)],
        [_source(accession, "0000000099")],
        status="fetch_failed",
    )
    progress = paths.progress_database_path("chunk-000000", "unfinished")
    progress.parent.mkdir(parents=True)
    progress.write_bytes(b"partial journal is deliberately unreadable")

    with pytest.raises(ValidationFailedError, match="refusing snapshot outcome status"):
        publish_committed_chunks(
            paths,
            run,
            cohort_accessions_path=paths.cohort_accessions_path(),
            cohort_sources_path=paths.cohort_sources_path(),
            expected_parent_snapshot_id=None,
        )
    assert DAGCatalog(InventoryPaths(tmp_path).snapshots_root).read_pointer() is None


def test_stale_parent_is_rejected_and_publication_lock_is_exclusive(
    tmp_path: Path,
) -> None:
    first = "0000000001-25-000001"
    second = "0000000002-26-000002"
    _paths, _run, published = _publish(
        tmp_path, "base-run", [first], [_source(first, "0000000099")]
    )
    assert published.snapshot is not None
    stale_paths, stale_run = _prepare_run(
        tmp_path,
        "stale-run",
        [IndexWorkItem(AccessionNumber(second), _url(second))],
        [_fact(first), _fact(second, date="2026-01-01")],
        [_source(first, "0000000099"), _source(second, "0000000099")],
        parent_id=None,
    )
    inventory_paths = InventoryPaths(tmp_path)
    with PublicationLock(inventory_paths):
        with pytest.raises(PublicationLockError):
            PublicationLock(inventory_paths, blocking=False)
    with pytest.raises(StaleParentError, match="expected parent"):
        publish_committed_chunks(
            stale_paths,
            stale_run,
            cohort_accessions_path=stale_paths.cohort_accessions_path(),
            cohort_sources_path=stale_paths.cohort_sources_path(),
            expected_parent_snapshot_id=None,
        )


def test_concurrent_publishers_serialize_and_refuse_the_loser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base_accession = "0000000001-25-000001"
    next_accessions = ["0000000002-26-000002", "0000000003-26-000003"]
    _paths, _run, published = _publish(
        tmp_path, "base-run", [base_accession], [_source(base_accession, "0000000099")]
    )
    assert published.snapshot is not None
    prepared = []
    for index, accession in enumerate(next_accessions):
        paths, run = _prepare_run(
            tmp_path,
            f"parallel-{index}",
            [IndexWorkItem(AccessionNumber(accession), _url(accession))],
            [_fact(base_accession), _fact(accession, date="2026-01-01")],
            [
                _source(base_accession, "0000000099"),
                _source(accession, "0000000099"),
            ],
            parent_id=published.snapshot.snapshot_id,
        )
        prepared.append((paths, run))

    rendezvous = Barrier(2)
    real_lock = publication_module.PublicationLock

    def concurrent_lock(*args, **kwargs):
        rendezvous.wait(timeout=30)
        return real_lock(*args, **kwargs)

    monkeypatch.setattr(publication_module, "PublicationLock", concurrent_lock)

    def publish(prepared_run):
        paths, run = prepared_run
        return publish_committed_chunks(
            paths,
            run,
            cohort_accessions_path=paths.cohort_accessions_path(),
            cohort_sources_path=paths.cohort_sources_path(),
            expected_parent_snapshot_id=published.snapshot.snapshot_id,
        )

    outcomes = []
    stale = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(publish, item) for item in prepared]
        for future in futures:
            try:
                outcomes.append(future.result(timeout=120))
            except StaleParentError as exc:
                stale.append(exc)
    assert len(outcomes) == 1
    assert outcomes[0].status == "published"
    assert len(stale) == 1
    pointer = DAGCatalog(InventoryPaths(tmp_path).snapshots_root).read_pointer()
    assert pointer is not None
    assert pointer["snapshot_id"] == outcomes[0].snapshot.snapshot_id


def test_refresh_replaces_active_entries_only_when_page_digest_changes(
    tmp_path: Path,
) -> None:
    accession = "0000000001-25-000001"
    _paths, _run, original = _publish(
        tmp_path,
        "base-run",
        [accession],
        [_source(accession, "0000000099")],
    )
    assert original.snapshot is not None
    unchanged_paths, unchanged_run = _prepare_run(
        tmp_path,
        "unchanged-refresh",
        [IndexWorkItem(AccessionNumber(accession), _url(accession))],
        [_fact(accession)],
        [_source(accession, "0000000099")],
        parent_id=original.snapshot.snapshot_id,
        refresh_mode="force",
    )
    unchanged = publish_committed_chunks(
        unchanged_paths,
        unchanged_run,
        cohort_accessions_path=unchanged_paths.cohort_accessions_path(),
        cohort_sources_path=unchanged_paths.cohort_sources_path(),
        expected_parent_snapshot_id=original.snapshot.snapshot_id,
    )
    assert unchanged.status == "no_op"

    changed_paths, changed_run = _prepare_run(
        tmp_path,
        "changed-refresh",
        [IndexWorkItem(AccessionNumber(accession), _url(accession))],
        [_fact(accession)],
        [_source(accession, "0000000099")],
        parent_id=original.snapshot.snapshot_id,
        refresh_mode="force",
        page_revision="changed",
    )
    changed = publish_committed_chunks(
        changed_paths,
        changed_run,
        cohort_accessions_path=changed_paths.cohort_accessions_path(),
        cohort_sources_path=changed_paths.cohort_sources_path(),
        expected_parent_snapshot_id=original.snapshot.snapshot_id,
    )
    assert changed.status == "published"
    assert any(
        p.path.endswith("entries/part-00000.parquet")
        for p in changed.snapshot.entries_partitions
    )
    refreshed_entries = get_active_entries(tmp_path, accession)
    assert len(refreshed_entries) == 1
    assert refreshed_entries[0]["document_label"] == "Annual report"


def test_complete_artifact_validation_detects_part_tampering(tmp_path: Path) -> None:
    accession = "0000000001-25-000001"
    _paths, _run, published = _publish(
        tmp_path, "tamper-run", [accession], [_source(accession, "0000000099")]
    )
    assert published.snapshot is not None
    part = (
        InventoryPaths(tmp_path).snapshot_root(published.snapshot.snapshot_id)
        / published.snapshot.accessions_partitions[0].path
    )
    part.write_bytes(b"changed")

    with pytest.raises(
        ValidationFailedError, match="size mismatch|unreadable|digest mismatch"
    ):
        validate_snapshot(InventoryPaths(tmp_path), published.snapshot.snapshot_id)
