"""Chunk checkpoint validation tests."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.domain.submissions.schemas import SUBMISSION_METADATA_SCHEMA
from edgar_sec.engine.submissions.builder import build_submission_table
from edgar_sec.pipelines.metadata_sync.checkpoints import (
    discover_completed_chunks,
    inspect_chunk,
    schema_matches,
)
from edgar_sec.pipelines.metadata_sync.manifest import read_cik_manifest
from edgar_sec.pipelines.metadata_sync.paths import resolve_run_paths
from edgar_sec.pipelines.metadata_sync.planner import build_plan
from tests.support import fixture_path


def _row(cik: str, fingerprint: str = "fp") -> dict:
    return {
        "cik": cik,
        "status": "ok",
        "input_fingerprint": fingerprint,
        "filings": [],
        "anomalies": [],
    }


def _write(path: Path, rows: list[dict], schema=SUBMISSION_METADATA_SCHEMA) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(build_submission_table(rows), path)
    return path


def _plan(tmp_path: Path, chunk_size: int = 2):
    manifest = read_cik_manifest(fixture_path("cik_sec_mini.csv"))
    plan = build_plan(manifest, chunk_size=chunk_size, partition_count=1)
    return plan, resolve_run_paths(plan["plan_id"], tmp_path)


def test_valid_checkpoint_is_accepted(tmp_path: Path) -> None:
    plan, run_paths = _plan(tmp_path)
    ciks = tuple(plan["chunks"][0]["cik_padded"])
    fp = plan["input_fingerprint"]
    _write(run_paths.chunk_file(0), [_row(cik, fp) for cik in ciks])

    completed = discover_completed_chunks(plan, run_paths)
    assert set(completed) == {0}
    assert completed[0].ciks == ciks
    assert completed[0].row_count == len(ciks)
    assert len(completed[0].file_sha256) == 64


def test_missing_checkpoint_is_absent(tmp_path: Path) -> None:
    plan, run_paths = _plan(tmp_path)
    assert discover_completed_chunks(plan, run_paths) == {}
    assert inspect_chunk(0, run_paths.chunk_file(0)) is None


def test_row_count_mismatch_is_rejected(tmp_path: Path) -> None:
    plan, run_paths = _plan(tmp_path)
    expected = tuple(plan["chunks"][0]["cik_padded"])
    _write(run_paths.chunk_file(0), [_row(expected[0])])

    completed = discover_completed_chunks(plan, run_paths)
    assert completed == {}


def test_foreign_fingerprint_is_rejected(tmp_path: Path) -> None:
    plan, run_paths = _plan(tmp_path)
    ciks = tuple(plan["chunks"][0]["cik_padded"])
    _write(run_paths.chunk_file(0), [_row(cik, "other-fp") for cik in ciks])

    assert discover_completed_chunks(plan, run_paths) == {}


def test_unexpected_cik_is_rejected(tmp_path: Path) -> None:
    plan, run_paths = _plan(tmp_path)
    expected = tuple(plan["chunks"][0]["cik_padded"])
    _write(run_paths.chunk_file(0), [_row("0000000001") for _ in expected])

    assert discover_completed_chunks(plan, run_paths) == {}


def test_schema_drift_is_rejected(tmp_path: Path) -> None:
    plan, run_paths = _plan(tmp_path)
    ciks = tuple(plan["chunks"][0]["cik_padded"])
    path = run_paths.chunk_file(0)
    path.parent.mkdir(parents=True, exist_ok=True)
    reduced = pa.schema([("cik", pa.string()), ("status", pa.string())])
    pq.write_table(
        pa.table({"cik": list(ciks), "status": ["ok"] * len(ciks)}, schema=reduced),
        path,
    )

    assert not schema_matches(path)
    assert discover_completed_chunks(plan, run_paths) == {}


def test_unreadable_file_is_rejected(tmp_path: Path) -> None:
    _unused_plan, run_paths = _plan(tmp_path)
    path = run_paths.chunk_file(0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not a parquet file")

    assert inspect_chunk(0, path) is None
