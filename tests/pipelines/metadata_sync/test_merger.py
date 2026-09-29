"""Coordinator merge validation and snapshot publication tests."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.domain.submissions.schemas import (
    SCHEMA_VERSION,
    SUBMISSION_METADATA_SCHEMA,
)
from edgar_sec.engine.submissions.builder import build_submission_table
from edgar_sec.pipelines.metadata_sync.manifest import read_cik_manifest
from edgar_sec.pipelines.metadata_sync.merger import (
    MergeError,
    merge_chunks,
    publish_snapshot,
)
from edgar_sec.pipelines.metadata_sync.paths import resolve_run_paths
from edgar_sec.pipelines.metadata_sync.planner import build_plan
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
    plan = build_plan(manifest, chunk_size=chunk_size, partition_count=1)
    return plan, resolve_run_paths(plan["plan_id"], tmp_path)


def _complete(plan, run_paths, *, fingerprint: str | None = None) -> None:
    fp = fingerprint if fingerprint is not None else plan["input_fingerprint"]
    for chunk in plan["chunks"]:
        rows = [_row(cik, fp) for cik in chunk["cik_padded"]]
        path = run_paths.chunk_file(int(chunk["chunk_id"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(build_submission_table(rows), path)


# ------------------------------------------------------------------ happy path


def test_merge_publishes_sorted_snapshot(tmp_path: Path) -> None:
    plan, run_paths = _plan(tmp_path)
    _complete(plan, run_paths)

    report = merge_chunks(plan, run_paths, "snap1")
    assert report.row_count == 4
    assert report.chunk_count == 2
    assert report.artifact_sha256
    assert report.filing_record_count == 0

    output = run_paths.metadata.snapshot_file("snap1")
    table = pq.read_table(output)
    assert table.schema.equals(SUBMISSION_METADATA_SCHEMA, check_metadata=False)
    assert table.column("cik").to_pylist() == sorted(table.column("cik").to_pylist())
    assert set(table.column("cik").to_pylist()) == set(plan["cik_padded"])


def test_publish_snapshot_writes_manifest_and_pointer(tmp_path: Path) -> None:
    plan, run_paths = _plan(tmp_path)
    _complete(plan, run_paths)
    report = merge_chunks(plan, run_paths, "snap1")
    manifest = publish_snapshot(report, run_paths.metadata)

    manifest_path = run_paths.metadata.snapshot_manifest("snap1")
    assert json.loads(manifest_path.read_text())["row_count"] == 4

    pointer = run_paths.metadata.current_pointer
    assert json.loads(pointer.read_text())["snapshot_id"] == "snap1"
    assert manifest["artifact_sha256"] == report.artifact_sha256


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
        "readback_done",
    ]
    assert events[0]["plan_id"] == plan["plan_id"]
    assert events[1]["chunks"] == 2
    assert events[-1]["rows"] == 4


def test_a_failing_progress_callback_does_not_fail_the_merge(tmp_path: Path) -> None:
    """Presentation must not be able to reject a validated snapshot."""
    plan, run_paths = _plan(tmp_path)
    _complete(plan, run_paths)

    def explode(_event: dict) -> None:
        raise RuntimeError("the progress bar is on fire")

    report = merge_chunks(plan, run_paths, "snap1", progress=explode)
    assert report.row_count == 4
    assert run_paths.metadata.snapshot_file("snap1").is_file()


def test_merge_records_the_plan_id_as_snapshot_identity(tmp_path: Path) -> None:
    """Snapshot identity is plan-derived, so rows and artifact cannot disagree."""
    plan, run_paths = _plan(tmp_path)
    for chunk in plan["chunks"]:
        rows = [_row(cik, plan["input_fingerprint"]) for cik in chunk["cik_padded"]]
        for row in rows:
            row["snapshot_id"] = plan["plan_id"]
        path = run_paths.chunk_file(int(chunk["chunk_id"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(build_submission_table(rows), path)

    report = merge_chunks(plan, run_paths, plan["plan_id"])

    assert report.snapshot_id == report.plan_id == plan["plan_id"]
    table = pq.read_table(run_paths.metadata.snapshot_file(plan["plan_id"]))
    assert set(table.column("snapshot_id").to_pylist()) == {plan["plan_id"]}
    assert report.to_dict()["schema_version"] == SCHEMA_VERSION


def test_merge_progress_is_optional(tmp_path: Path) -> None:
    plan, run_paths = _plan(tmp_path)
    _complete(plan, run_paths)
    assert merge_chunks(plan, run_paths, "snap1").row_count == 4


# --------------------------------------------------------------- hard failures


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
        build_submission_table([_row("0000000007", plan["input_fingerprint"])]), path
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
    fp = plan["input_fingerprint"]
    for chunk in plan["chunks"]:
        rows = [_row("0000000001", fp) for _ in chunk["cik_padded"]]
        path = run_paths.chunk_file(int(chunk["chunk_id"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(build_submission_table(rows), path)
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
    ciks = [None, *plan["chunks"][0]["cik_padded"][1:]]
    pq.write_table(
        build_submission_table([_row(cik, plan["input_fingerprint"]) for cik in ciks]),
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
    ciks = plan["chunks"][0]["cik_padded"]
    pq.write_table(
        build_submission_table([_row(ciks[0], plan["input_fingerprint"])]), path
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
            {"cik": plan["chunks"][0]["cik_padded"], "status": ["ok", "ok"]},
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
    path = run_paths.chunk_file(0)
    ciks = plan["chunks"][0]["cik_padded"]
    pq.write_table(
        build_submission_table(
            [_row(cik, plan["input_fingerprint"], status="pending") for cik in ciks]
        ),
        path,
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
    fp = plan["input_fingerprint"]
    for chunk in plan["chunks"]:
        rows = [_row(cik, fp, accession=ACCESSION) for cik in chunk["cik_padded"]]
        path = run_paths.chunk_file(int(chunk["chunk_id"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(build_submission_table(rows), path)

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
