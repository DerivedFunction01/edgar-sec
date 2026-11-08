"""Verify: reconciled loads pass; the BDC population comparison reports."""

from __future__ import annotations

import csv
from pathlib import Path

from edgar_sec.pipelines.datasets.ingest import import_local_archive
from edgar_sec.pipelines.datasets.paths import resolve_datasets_paths
from edgar_sec.pipelines.datasets.specs import spec_for
from edgar_sec.pipelines.datasets.store import load_bdc_population, open_store
from edgar_sec.pipelines.datasets.verify import verify_store
from tests.support import fixture_path


def test_verify_passes_for_a_reconciled_specimen(tmp_path: Path) -> None:
    paths = resolve_datasets_paths(tmp_path)
    import_local_archive(
        paths,
        spec_for("mfrr"),
        "2010q4",
        fixture_path("datasets/mfrr_2010q4_specimen.zip"),
        source_url="https://www.sec.gov/example.zip",
        loaded_at="2026-11-08T00:00:00+00:00",
    )
    result = verify_store(paths.store_file)
    assert result.ok
    assert result.tables
    assert result.population == ()


def test_verify_reports_population_overlap(tmp_path: Path) -> None:
    paths = resolve_datasets_paths(tmp_path)
    import_local_archive(
        paths,
        spec_for("bdc"),
        "2026_01",
        fixture_path("datasets/bdc_2026_01_specimen.zip"),
        source_url="https://www.sec.gov/example.zip",
        loaded_at="2026-11-08T00:00:00+00:00",
    )
    report = tmp_path / "report.csv"
    with open(report, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["File_No", "CIK", "Registrant_Name"])
        writer.writerow(["814-001", "999999999", "NOT IN DATASET"])
    con = open_store(paths.store_file)
    try:
        load_bdc_population(con, {2026: report}, loaded_at="2026-11-08T00:00:00+00:00")
    finally:
        con.close()
    result = verify_store(paths.store_file)
    assert result.ok
    assert len(result.population) == 1
    check = result.population[0]
    assert check.vintage == "2026_01"
    assert check.report_ciks == 1
    assert check.both == 0
    assert check.report_only == 1
    assert check.dataset_ciks > 0
    assert check.dataset_only == check.dataset_ciks
