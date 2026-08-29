"""End-to-end Phase 2.5 pipeline test (offline fixture mode)."""

from __future__ import annotations

import importlib
import uuid
from pathlib import Path

from defs.sql import Select, SqlDialect, Table, col, make_sql_executor

pipeline = importlib.import_module("phases.025_webpage_storage.core.pipeline")
phases_025 = importlib.import_module("phases.025_webpage_storage.core.schemas")
merge_partition = importlib.import_module(
    "phases.025_webpage_storage.core.partition_merger"
).merge_partition


def test_pipeline_fixture_run_writes_partition_database(
    phase02_bundle: Path, fixture_database: Path, tmp_path: Path
):
    output_dir = tmp_path / "out"
    result = pipeline.run_partition(
        phase02_bundle,
        output_dir,
        mode="fixture",
        fixture_paths=[fixture_database],
        run_id="test-run",
        partition_id=1,
        partition_count=1,
        chunk_size=100,
    )

    assert result["locator_count"] == 2
    assert result["occurrence_count"] == 2
    assert not result["failures"]
    partition_db = output_dir / "partition-00001.sqlite"
    assert partition_db.is_file()

    executor = make_sql_executor(partition_db, dialect=SqlDialect.SQLITE)
    try:
        blobs = executor.query(
            executor.compiler.compile(
                Select(
                    source=Table(phases_025.DOCUMENT_BLOBS_TABLE),
                    projection=(col("doc_id"),),
                )
            )
        )
        occurrences = executor.query(
            executor.compiler.compile(
                Select(
                    source=Table(phases_025.FILING_OCCURRENCES_TABLE),
                    projection=(col("occurrence_id"),),
                )
            )
        )
    finally:
        executor.close()

    assert len(blobs) == 2
    assert len(occurrences) == 2

    # The produced partition database is itself a valid merge source.
    second = tmp_path / "remerge.db"
    second.touch()
    remerge = merge_partition(second, [partition_db])
    assert remerge.blob_rows == 2
    assert len(remerge.committed_chunk_ids) == 1


def test_pipeline_multi_worker_parallel_execution(
    phase02_bundle: Path, fixture_database: Path, tmp_path: Path
):
    output_dir = tmp_path / "out_multi"
    result = pipeline.run_partition(
        phase02_bundle,
        output_dir,
        mode="fixture",
        fixture_paths=[fixture_database],
        run_id="multi-worker-run",
        partition_id=1,
        partition_count=1,
        chunk_size=1,
        workers=2,
    )

    assert result["locator_count"] == 2
    assert result["occurrence_count"] == 2
    assert len(result["chunks"]) == 2
    assert not result["failures"]
    partition_db = output_dir / "partition-00001.sqlite"
    assert partition_db.is_file()

    executor = make_sql_executor(partition_db, dialect=SqlDialect.SQLITE)
    try:
        blobs = executor.query(
            executor.compiler.compile(
                Select(
                    source=Table(phases_025.DOCUMENT_BLOBS_TABLE),
                    projection=(col("doc_id"),),
                )
            )
        )
        chunks = executor.query(
            executor.compiler.compile(
                Select(
                    source=Table(phases_025.COMMITTED_CHUNKS_TABLE),
                    projection=(col("chunk_id"),),
                )
            )
        )
    finally:
        executor.close()

    assert len(blobs) == 2
    assert len(chunks) == 2


def test_pipeline_resuming_with_worker_count_change(
    phase02_bundle: Path, fixture_database: Path, tmp_path: Path
):
    output_dir = tmp_path / "out_resume"
    # First run with 1 worker
    first_result = pipeline.run_partition(
        phase02_bundle,
        output_dir,
        mode="fixture",
        fixture_paths=[fixture_database],
        run_id="resume-run",
        partition_id=1,
        partition_count=1,
        chunk_size=1,
        workers=1,
    )
    assert len(first_result["chunks"]) == 2

    # Second run with 4 workers: preflight detects existing completed chunks
    second_result = pipeline.run_partition(
        phase02_bundle,
        output_dir,
        mode="fixture",
        fixture_paths=[fixture_database],
        run_id="resume-run",
        partition_id=1,
        partition_count=1,
        chunk_size=1,
        workers=4,
    )
    assert len(second_result["chunks"]) == 2
    assert second_result["occurrence_count"] == 2


def test_pipeline_surfaces_acquisition_failures(tmp_path: Path, fixture_database: Path):
    from .conftest import build_phase02_bundle

    # Bundle has 1 existing doc and 1 missing doc
    bundle = build_phase02_bundle(
        tmp_path / "plan_with_missing",
        documents={"000000000100000001/10k.htm": b"<html>alpha</html>"},
        occurrences=[
            {
                "occurrence_id": "occ-ok",
                "document_locator_key": "loc-ok",
                "source_cik": "0000000001",
                "accession": "000000000100000001",
                "form": "10-K",
                "filing_date": "2024-01-02",
                "report_date": "2023-12-31",
                "document_path": "10k.htm",
            },
            {
                "occurrence_id": "occ-missing",
                "document_locator_key": "loc-missing",
                "source_cik": "0000000001",
                "accession": "000000000100000001",
                "form": "10-K",
                "filing_date": "2024-01-02",
                "report_date": "2023-12-31",
                "document_path": "nonexistent.htm",
            },
        ],
    )

    output_dir = tmp_path / "out_failures"
    result = pipeline.run_partition(
        bundle,
        output_dir,
        mode="fixture",
        fixture_paths=[fixture_database],
        run_id="failure-run",
        partition_id=1,
        partition_count=1,
        chunk_size=2,
        workers=2,
    )

    assert len(result["failures"]) == 1
    assert result["failures"][0]["status"] == "missing"
    assert result["blob_count" if "blob_count" in result else "occurrence_count"] == 1

    partition_db = output_dir / "partition-00001.sqlite"
    executor = make_sql_executor(partition_db, dialect=SqlDialect.SQLITE)
    try:
        failures_in_db = executor.query(
            executor.compiler.compile(
                Select(
                    source=Table(phases_025.ACQUISITION_FAILURES_TABLE),
                    projection=(col("doc_id"), col("status")),
                )
            )
        )
    finally:
        executor.close()

    assert len(failures_in_db) == 1
    assert failures_in_db[0]["status"] == "missing"


def test_calculate_optimal_chunk_size():
    calc = pipeline.calculate_optimal_chunk_size
    assert calc(0) == 100
    assert calc(50, workers=1) == 100
    assert calc(500, workers=2) == 100  # 500 / 8 = 63 -> clamped to 100
    assert calc(5000, workers=8) == 157  # 5000 / 32 = 157
    assert calc(50000, workers=8) == 1563  # 50000 / 32 = 1563
    assert calc(500000, workers=8) == 2500  # clamped to 2500 max


def test_pipeline_progress_callback(
    phase02_bundle: Path, fixture_database: Path, tmp_path: Path
):
    events: list[dict] = []
    output_dir = tmp_path / "out_prog"
    result = pipeline.run_partition(
        phase02_bundle,
        output_dir,
        mode="fixture",
        fixture_paths=[fixture_database],
        run_id=f"prog-run-{uuid.uuid4().hex}",
        partition_id=1,
        partition_count=1,
        chunk_size=1,
        workers=2,
        progress=events.append,
    )
    assert len(result["chunks"]) == 2
    assert len(events) >= 2
    assert any(
        e["type"] == "document_done" and e["status"] in ("ok", "missing")
        for e in events
    )
