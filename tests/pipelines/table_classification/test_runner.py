"""Tests for the run machinery over an empty snapshot."""

from __future__ import annotations

from edgar_sec.infra.storage.parquet import read_parquet_table
from edgar_sec.pipelines.table_classification.runner import run_plan

from .support import make_plan


def test_run_over_empty_snapshot_merges_absences(tmp_path) -> None:  # noqa: ANN001
    paths, plan = make_plan(tmp_path)
    report = run_plan(paths, plan.plan_id, workers=1)
    assert report.work_items == 2
    assert report.merge.filing_count == 2
    assert report.merge.geometry_count == 0
    merged = paths.merged_dir(plan.plan_id)
    records = read_parquet_table(merged / "filing_records.parquet").to_pylist()
    assert all(row["status"] == "no_documents" for row in records)
    assert all(row["absence_reason"] == "not_in_snapshot" for row in records)
