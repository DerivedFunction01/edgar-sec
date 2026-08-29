"""End-to-end Phase 2.5 pipeline test (offline fixture mode)."""

from __future__ import annotations

import importlib
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
