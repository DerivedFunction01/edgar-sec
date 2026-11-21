"""Tests for run merge validation and assembly."""

from __future__ import annotations

import pytest

from edgar_sec.infra.storage.parquet import read_parquet_table
from edgar_sec.pipelines.table_classification.merger import MergeError, merge_run
from edgar_sec.pipelines.table_classification.worker import classify_work_item

from .support import FakeSource, make_plan, primary_payload

ACCESSION = "0000000001-26-000001"
ACCESSION_2 = "0000000002-26-000001"


def _stage_all(paths, plan) -> None:  # noqa: ANN001
    source = FakeSource(
        {
            ACCESSION: (primary_payload(),),
            ACCESSION_2: (primary_payload("quarter.htm"),),
        }
    )
    for item in plan.work_items:
        classify_work_item(plan, item, source, paths)


def test_merge_assembles_run_outputs(tmp_path) -> None:  # noqa: ANN001
    paths, plan = make_plan(tmp_path)
    _stage_all(paths, plan)
    report = merge_run(paths, plan)
    assert report.filing_count == 2
    assert report.geometry_count == 6
    assert report.classified_count == 6
    merged = paths.merged_dir(plan.plan_id)
    assert (merged / "run_manifest.json").is_file()
    records = read_parquet_table(merged / "filing_records.parquet").to_pylist()
    assert {row["accession"] for row in records} == {ACCESSION, ACCESSION_2}
    assert all(row["status"] == "classified" for row in records)


def test_merge_refuses_a_missing_work_item(tmp_path) -> None:  # noqa: ANN001
    paths, plan = make_plan(tmp_path)
    source = FakeSource({ACCESSION: (primary_payload(),)})
    classify_work_item(plan, plan.work_items[0], source, paths)
    with pytest.raises(MergeError):
        merge_run(paths, plan)
