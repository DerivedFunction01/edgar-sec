"""Coordinator merge validation and snapshot publication tests."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from edgar_sec.domain.submissions.schemas import (
    SCHEMA_VERSION,
    SUBMISSION_METADATA_SCHEMA,
)
from edgar_sec.engine.submissions.builder import build_submission_table
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.parquet import count_parquet_rows
from edgar_sec.pipelines.metadata_sync.augmentation import derive_delta_plan
from edgar_sec.pipelines.metadata_sync.manifest import read_cik_manifest
from edgar_sec.pipelines.metadata_sync.merger import (
    MergeError,
    merge_chunks,
    publish_snapshot,
)
from edgar_sec.pipelines.metadata_sync.paths import resolve_run_paths
from edgar_sec.pipelines.metadata_sync.planner import build_plan
from edgar_sec.pipelines.metadata_sync.roster import (
    build_roster,
    read_cik_index,
    roster_from_manifest,
)
from edgar_sec.pipelines.metadata_sync.snapshot import (
    SNAPSHOT_MANIFEST_VERSION,
    read_snapshot_parts,
)
from tests.support import fixture_path

ACCESSION = "0000037996-26-000039"
ACCESSION_NORM = "000003799626000039"


def _row(
    cik: str,
    fingerprint: str,
    *,
    accession: str | None = None,
    status: str = "ok",
) -> dict:
    filings = (
        [
            {
                "accession_number": accession,
                "accession_number_normalized": accession.replace("-", ""),
                "filing_date": "2026-02-05",
                "report_date": "2025-12-31",
                "acceptance_datetime": "2026-02-05T18:04:21.431Z",
                "act": "34",
                "form": "10-K",
                "file_number": "001-00405",
                "film_number": "26551234",
                "items": ["10-K"],
                "core_type": None,
                "size": 3380161,
                "is_xbrl": True,
                "is_inline_xbrl": True,
                "is_xbrl_numeric": False,
                "primary_document": "f-20251231.htm",
                "primary_doc_description": "10-K",
                "archive_url": None,
                "source_section": "recent",
                "source_file": "u",
                "source_array_index": 0,
            }
        ]
        if accession
        else []
    )
    return {
        "cik": cik,
        "status": status,
        "input_fingerprint": fingerprint,
        "filings": filings,
        "anomalies": [],
    }


def _plan(tmp_path: Path, chunk_size: int = 2):
    manifest = read_cik_manifest(fixture_path("cik_sec_mini.csv"))
    plan = build_plan(
        roster_from_manifest(manifest),
        chunk_size=chunk_size,
        input_name=manifest.input_name,
        input_fingerprint=manifest.input_fingerprint,
    )
    return plan, resolve_run_paths(plan.plan_id, tmp_path)


def _write_chunk(run_paths, chunk_id: int, rows: list[dict]) -> None:
    path = run_paths.chunk_file(chunk_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(build_submission_table(rows), path)


def _complete(plan, run_paths, *, fingerprint: str | None = None) -> None:
    fp = fingerprint if fingerprint is not None else plan.input_fingerprint
    for chunk_id in plan.chunk_ids():
        _write_chunk(
            run_paths, chunk_id, [_row(cik, fp) for cik in plan.chunk_ciks(chunk_id)]
        )


# ------------------------------------------------------------------ happy path


def test_merge_publishes_a_multipart_snapshot(tmp_path: Path) -> None:
    """A snapshot is an ordered set of parts, not one rewritten monolith.

    Parts are byte copies of the validated chunks, so the published dataset is in
    chunk order rather than globally CIK-sorted. The manifest says so explicitly
    so a consumer cannot mistake one for the other.
    """
    plan, run_paths = _plan(tmp_path)
    _complete(plan, run_paths)

    report = merge_chunks(plan, run_paths, "snap1")
    assert report.row_count == 4
    assert report.chunk_count == 2
    assert report.part_count == 2
    assert report.filing_record_count == 0

    publish_snapshot(report, run_paths.metadata)
    parts = read_snapshot_parts(run_paths.metadata.snapshot_manifest("snap1"))
    assert parts.part_count == 2
    assert [part["part_index"] for part in report.parts] == [0, 1]
    assert [part["source"] for part in report.parts] == [
        "chunk:chunk_0000",
        "chunk:chunk_0001",
    ]
    assert report.to_dict()["sort_order"] == "chunk_order"

    ciks: list[str] = []
    for path in parts.paths:
        table = pq.read_table(path)
        assert table.schema.equals(SUBMISSION_METADATA_SCHEMA, check_metadata=False)
        ciks.extend(table.column("cik").to_pylist())
    assert set(ciks) == set(plan.roster.ciks)
    assert len(ciks) == plan.row_count


def test_published_parts_are_byte_copies_of_the_validated_chunks(
    tmp_path: Path,
) -> None:
    """Publication must not re-materialize rows it already validated."""
    plan, run_paths = _plan(tmp_path)
    _complete(plan, run_paths)
    report = merge_chunks(plan, run_paths, "snap1")

    for index, part in enumerate(report.parts):
        source = run_paths.chunk_file(index)
        assert part["sha256"] == file_sha256(source)
        assert part["row_count"] == count_parquet_rows(source)
        assert part["byte_count"] == source.stat().st_size


def test_multipart_manifest_names_no_single_payload(tmp_path: Path) -> None:
    """A legacy reader must fail loudly rather than ingest only the first part.

    Pointing ``output_path`` at part zero would let a reader that understands
    only the singular shape silently read a fraction of the dataset, so the
    singular fields stay empty and the part list is authoritative.
    """
    plan, run_paths = _plan(tmp_path)
    _complete(plan, run_paths)
    manifest = publish_snapshot(
        merge_chunks(plan, run_paths, "snap1"), run_paths.metadata
    )

    assert manifest["output_path"] == ""
    assert manifest["artifact_sha256"] == ""
    assert manifest["part_count"] == 2
    assert manifest["manifest_version"] == SNAPSHOT_MANIFEST_VERSION
    assert [part["path"] for part in manifest["parts"]] == [
        "parts/part-00000.parquet",
        "parts/part-00001.parquet",
    ]

    pointer = json.loads(run_paths.metadata.current_pointer.read_text(encoding="utf-8"))
    assert pointer["part_count"] == 2
    assert pointer["parts_digest"] == manifest["parts_digest"]
    assert "artifact_sha256" not in pointer


def test_publish_snapshot_writes_manifest_and_pointer(tmp_path: Path) -> None:
    plan, run_paths = _plan(tmp_path)
    _complete(plan, run_paths)
    report = merge_chunks(plan, run_paths, "snap1")
    manifest = publish_snapshot(report, run_paths.metadata)

    manifest_path = run_paths.metadata.snapshot_manifest("snap1")
    assert json.loads(manifest_path.read_text())["row_count"] == 4

    pointer = json.loads(run_paths.metadata.current_pointer.read_text(encoding="utf-8"))
    assert pointer["snapshot_id"] == "snap1"
    assert manifest["parts_digest"] == report.parts_digest


# ------------------------------------------------------------------- progress


def test_merge_emits_progress_events(tmp_path: Path) -> None:
    """A merge over millions of rows is long enough that silence reads as a hang."""
    plan, run_paths = _plan(tmp_path)
    _complete(plan, run_paths)
    events: list[dict] = []

    merge_chunks(plan, run_paths, "snap1", progress=events.append)

    assert [event["type"] for event in events] == [
        "merge_start",
        "chunks_validated",
        "merge_stage",
        "cik_index",
        "readback_done",
    ]
    assert events[0]["plan_id"] == plan.plan_id
    assert events[1]["chunks"] == 2
    assert events[-1]["rows"] == 4


def test_published_cik_index_matches_the_payload(tmp_path: Path) -> None:
    """The index is a statement about the artifact on disk.

    It is derived from the published rows rather than from the request, so a
    plan that asked for something the merge did not deliver shows up here rather
    than in a later consumer's row count.
    """
    plan, run_paths = _plan(tmp_path)
    _complete(plan, run_paths)
    report = merge_chunks(plan, run_paths, "snap1")
    publish_snapshot(report, run_paths.metadata)

    index = read_cik_index(run_paths.metadata.snapshot_cik_index("snap1"))
    parts = read_snapshot_parts(run_paths.metadata.snapshot_manifest("snap1"))
    published: list[str] = []
    for path in parts.paths:
        published.extend(pq.read_table(path, columns=["cik"]).column("cik").to_pylist())
    assert list(index) == sorted(set(published))
    assert report.cik_count == len(index)
    assert report.cik_index_sha256
    assert report.cik_index_path.endswith("ciks.parquet")


def test_snapshot_manifest_records_lineage_beside_the_parts(
    tmp_path: Path,
) -> None:
    """Lineage and the CIK index travel with the part list."""
    plan, run_paths = _plan(tmp_path)
    _complete(plan, run_paths)
    manifest = publish_snapshot(
        merge_chunks(plan, run_paths, "snap1"), run_paths.metadata
    )

    assert manifest["cik_index_sha256"]
    assert manifest["cik_count"] == 4
    assert manifest["roster_id"] == plan.roster.roster_id
    assert manifest["kind"] == "full"
    assert manifest["parent_snapshot_id"] == ""

    on_disk = json.loads(
        run_paths.metadata.snapshot_manifest("snap1").read_text(encoding="utf-8")
    )
    assert on_disk["parts_digest"] == manifest["parts_digest"]
    assert len(on_disk["parts"]) == 2


def test_a_failing_progress_callback_does_not_fail_the_merge(tmp_path: Path) -> None:
    """Presentation must not be able to reject a validated snapshot."""
    plan, run_paths = _plan(tmp_path)
    _complete(plan, run_paths)

    def explode(_event: dict) -> None:
        raise RuntimeError("the progress bar is on fire")

    report = merge_chunks(plan, run_paths, "snap1", progress=explode)
    assert report.row_count == 4
    assert report.part_count == 2
    for part in report.parts:
        assert (run_paths.metadata.snapshot_dir("snap1") / part["path"]).is_file()


def test_merge_records_the_plan_id_as_snapshot_identity(tmp_path: Path) -> None:
    """Snapshot identity is plan-derived, so rows and artifact cannot disagree."""
    plan, run_paths = _plan(tmp_path)
    for chunk_id in plan.chunk_ids():
        rows = [_row(cik, plan.input_fingerprint) for cik in plan.chunk_ciks(chunk_id)]
        for row in rows:
            row["snapshot_id"] = plan.plan_id
        _write_chunk(run_paths, chunk_id, rows)

    report = merge_chunks(plan, run_paths, plan.plan_id)
    publish_snapshot(report, run_paths.metadata)

    assert report.snapshot_id == report.plan_id == plan.plan_id
    parts = read_snapshot_parts(run_paths.metadata.snapshot_manifest(plan.plan_id))
    stamped: set[str] = set()
    for path in parts.paths:
        table = pq.read_table(path, columns=["snapshot_id"])
        stamped.update(table.column("snapshot_id").to_pylist())
    assert stamped == {plan.plan_id}
    assert report.to_dict()["schema_version"] == SCHEMA_VERSION


def test_merge_progress_is_optional(tmp_path: Path) -> None:
    plan, run_paths = _plan(tmp_path)
    _complete(plan, run_paths)
    assert merge_chunks(plan, run_paths, "snap1").row_count == 4


# --------------------------------------------------------------- hard failures


def test_a_delta_plan_cannot_be_merged_on_its_own(tmp_path: Path) -> None:
    """A plain merge over a delta plan would silently drop the base.

    ``merge_chunks`` publishes exactly the chunks a plan produced, and a delta
    plan's chunks hold only the CIKs its base is missing. Because the delta plan
    id is also the snapshot id an augmentation publishes under, a generic merge
    over it would rewrite that same snapshot manifest with a delta-only payload
    and advance the current pointer onto it -- destroying the base rows the
    manifest names as its parent. Recombining base and delta is augmentation's
    job, so the refusal belongs here.
    """
    manifest = read_cik_manifest(fixture_path("cik_sec_mini.csv"))
    delta = derive_delta_plan(
        roster_from_manifest(manifest),
        build_roster(manifest.ciks[:1]),
        chunk_size=2,
        base_snapshot_id="base-snap",
    )
    run_paths = resolve_run_paths(delta.plan_id, tmp_path)
    _complete(delta, run_paths)
    with pytest.raises(MergeError) as excinfo:
        merge_chunks(delta, run_paths, delta.plan_id)
    message = str(excinfo.value)
    assert "delta plan" in message
    assert "base-snap" in message
    assert "metadata augment" in message
    # Nothing was published as a side effect of the refusal.
    assert not (tmp_path / "metadata" / "snapshots" / delta.plan_id).exists()


def test_missing_chunk_rejected(tmp_path: Path) -> None:
    plan, run_paths = _plan(tmp_path)
    _complete(plan, run_paths)
    run_paths.chunk_file(1).unlink()
    try:
        merge_chunks(plan, run_paths, "snap1")
    except MergeError as exc:
        assert "missing chunk checkpoints" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected MergeError")


def test_foreign_chunk_file_rejected(tmp_path: Path) -> None:
    plan, run_paths = _plan(tmp_path)
    _complete(plan, run_paths)
    path = run_paths.chunk_file(7)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        build_submission_table([_row("0000000007", plan.input_fingerprint)]), path
    )
    try:
        merge_chunks(plan, run_paths, "snap1")
    except MergeError as exc:
        assert "outside the plan" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected MergeError")


def test_wrong_cik_is_rejected_by_coverage_guard(tmp_path: Path) -> None:
    """Coverage is validated before the DuckDB duplicate-key probe.

    A chunk that does not carry exactly its planned CIKs is rejected on
    coverage, which is what actually prevents duplicate CIKs from ever
    reaching the merged dataset. The DuckDB probe is defense in depth for
    the cross-chunk case, exercised directly below.
    """
    plan, run_paths = _plan(tmp_path)
    fp = plan.input_fingerprint
    for chunk_id in plan.chunk_ids():
        _write_chunk(
            run_paths,
            chunk_id,
            [_row("0000000001", fp) for _ in plan.chunk_ciks(chunk_id)],
        )
    try:
        merge_chunks(plan, run_paths, "snap1")
    except MergeError as exc:
        assert "CIK coverage differs from the plan" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected MergeError")


def test_find_duplicate_keys_flags_cross_chunk_duplicates(tmp_path: Path) -> None:
    from edgar_sec.infra.storage.duckdb import connect, find_duplicate_keys

    paths = []
    for index in range(2):
        path = tmp_path / f"chunk_{index}.parquet"
        pq.write_table(build_submission_table([_row("0000000001", "fp")]), path)
        paths.append(str(path))

    con = connect()
    try:
        assert find_duplicate_keys(con, paths, "cik") == ["0000000001"]
    finally:
        con.close()


def test_null_cik_rejected_by_coverage_guard(tmp_path: Path) -> None:
    plan, run_paths = _plan(tmp_path)
    _complete(plan, run_paths)
    path = run_paths.chunk_file(0)
    ciks = [None, *plan.chunk_ciks(0)[1:]]
    pq.write_table(
        build_submission_table([_row(cik, plan.input_fingerprint) for cik in ciks]),
        path,
    )
    try:
        merge_chunks(plan, run_paths, "snap1")
    except MergeError as exc:
        assert "CIK coverage differs from the plan" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected MergeError")


def test_find_null_keys_counts_null_ciks(tmp_path: Path) -> None:
    from edgar_sec.infra.storage.duckdb import connect, find_null_keys

    path = tmp_path / "nulls.parquet"
    pq.write_table(
        build_submission_table(
            [_row("0000000001", "fp"), _row(None, "fp"), _row("0000000002", "fp")]
        ),
        path,
    )
    con = connect()
    try:
        assert find_null_keys(con, [str(path)], "cik") == 1
    finally:
        con.close()


def test_foreign_fingerprint_rejected(tmp_path: Path) -> None:
    plan, run_paths = _plan(tmp_path)
    _complete(plan, run_paths, fingerprint="some-other-input")
    try:
        merge_chunks(plan, run_paths, "snap1")
    except MergeError as exc:
        assert "foreign input fingerprint" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected MergeError")


def test_row_count_mismatch_rejected(tmp_path: Path) -> None:
    plan, run_paths = _plan(tmp_path)
    _complete(plan, run_paths)
    path = run_paths.chunk_file(0)
    ciks = plan.chunk_ciks(0)
    pq.write_table(
        build_submission_table([_row(ciks[0], plan.input_fingerprint)]), path
    )
    try:
        merge_chunks(plan, run_paths, "snap1")
    except MergeError as exc:
        assert "row count" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected MergeError")


def test_schema_drift_rejected(tmp_path: Path) -> None:
    plan, run_paths = _plan(tmp_path)
    _complete(plan, run_paths)
    path = run_paths.chunk_file(0)
    reduced = pa.schema([("cik", pa.string()), ("status", pa.string())])
    pq.write_table(
        pa.table(
            {"cik": list(plan.chunk_ciks(0)), "status": ["ok", "ok"]},
            schema=reduced,
        ),
        path,
    )
    try:
        merge_chunks(plan, run_paths, "snap1")
    except MergeError as exc:
        assert "schema drifted" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected MergeError")


def test_non_terminal_status_rejected(tmp_path: Path) -> None:
    plan, run_paths = _plan(tmp_path)
    _complete(plan, run_paths)
    _write_chunk(
        run_paths,
        0,
        [
            _row(cik, plan.input_fingerprint, status="pending")
            for cik in plan.chunk_ciks(0)
        ],
    )
    try:
        merge_chunks(plan, run_paths, "snap1")
    except MergeError as exc:
        assert "non-terminal statuses" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected MergeError")


# ------------------------------------------------------------------- warnings


def test_duplicate_accessions_warn_but_do_not_fail(tmp_path: Path) -> None:
    plan, run_paths = _plan(tmp_path)
    fp = plan.input_fingerprint
    for chunk_id in plan.chunk_ids():
        _write_chunk(
            run_paths,
            chunk_id,
            [_row(cik, fp, accession=ACCESSION) for cik in plan.chunk_ciks(chunk_id)],
        )

    report = merge_chunks(plan, run_paths, "snap1")
    assert report.row_count == 4
    assert ACCESSION in report.duplicate_accessions
    assert any("not globally unique" in w for w in report.warnings)
    assert report.filing_record_count == 4


def test_no_duplicate_warning_on_clean_merge(tmp_path: Path) -> None:
    plan, run_paths = _plan(tmp_path)
    _complete(plan, run_paths)
    report = merge_chunks(plan, run_paths, "snap1")
    assert report.duplicate_accessions == []
    assert report.warnings == []
