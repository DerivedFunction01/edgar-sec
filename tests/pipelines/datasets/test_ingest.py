"""Ingest: local-archive import archives by hash and loads; population rows."""

from __future__ import annotations

import csv
from pathlib import Path

from edgar_sec.infra.storage.bulk_archive import BulkArchiveStore
from edgar_sec.pipelines.datasets.ingest import import_local_archive
from edgar_sec.pipelines.datasets.paths import resolve_datasets_paths
from edgar_sec.pipelines.datasets.specs import spec_for
from edgar_sec.pipelines.datasets.store import load_bdc_population, open_store
from tests.support import fixture_path


def test_import_local_archive_stores_and_loads(tmp_path: Path) -> None:
    paths = resolve_datasets_paths(tmp_path)
    result = import_local_archive(
        paths,
        spec_for("mfrr"),
        "2010q4",
        fixture_path("datasets/mfrr_2010q4_specimen.zip"),
        source_url="https://www.sec.gov/files/dera/data/mutual-fund-prospectus-risk/return-summary-data-sets/2010q4_rr1.zip",
        loaded_at="2026-11-08T00:00:00+00:00",
    )
    assert len(result.archive_sha) == 64
    store = BulkArchiveStore(paths.bulk_archives_root)
    assert store.open("mfrr_datasets", result.archive_sha) is not None
    con = open_store(paths.store_file)
    try:
        count = con.execute("SELECT count(*) FROM mfrr_sub").fetchone()[0]
    finally:
        con.close()
    assert count == 2


def test_bdc_population_normalizes_yearly_spellings(tmp_path: Path) -> None:
    path = tmp_path / "business-development-company-2026.csv"
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "File_No",
                "CIK",
                "Registrant_Name",
                "City",
                "State",
                "Zip_Code",
                "Filing Date",
                "Filing Type",
            ]
        )
        writer.writerow(
            [
                "814-001",
                "1287750",
                "ARES CAPITAL CORP",
                "New York",
                "NY",
                "10019",
                "05/29/26",
                "10-Q",
            ]
        )
        writer.writerow(
            [
                "814-002",
                "12345",
                "EXAMPLE BDC",
                "Boston",
                "MA",
                "02110",
                "04/01/26",
                "10-K",
            ]
        )
    paths = resolve_datasets_paths(tmp_path)
    con = open_store(paths.store_file)
    try:
        loaded = load_bdc_population(
            con, {2026: path}, loaded_at="2026-11-08T00:00:00+00:00"
        )
        rows = con.execute(
            "SELECT cik, registrant_name FROM bdc_population ORDER BY cik"
        ).fetchall()
    finally:
        con.close()
    assert loaded == 2
    assert rows == [
        ("0000012345", "EXAMPLE BDC"),
        ("0001287750", "ARES CAPITAL CORP"),
    ]


class _ReportHttp:
    """Offline double serving one BDC Report CSV per requested year."""

    def get_bytes(self, url: str) -> bytes:
        year = url.rsplit("-", 1)[-1].removesuffix(".csv")
        return (
            "File_No,CIK,Registrant_Name,City,State,Zip_Code,"
            "Filing Date,Filing Type\n"
            f"814-001,{year}001,EXAMPLE {year},Boston,MA,02110,04/01/26,10-K\n"
        ).encode()


def test_import_bdc_population_archives_csvs_and_loads(tmp_path: Path) -> None:
    from edgar_sec.pipelines.datasets.ingest import import_bdc_population

    paths = resolve_datasets_paths(tmp_path)
    loaded = import_bdc_population(
        paths,
        (2026, 2025, 2024),
        http=_ReportHttp(),  # type: ignore[arg-type]
        loaded_at="2026-11-08T00:00:00+00:00",
    )
    assert loaded == 3
    con = open_store(paths.store_file)
    try:
        rows = con.execute(
            "SELECT cik, report_year FROM bdc_population ORDER BY report_year"
        ).fetchall()
    finally:
        con.close()
    assert rows == [
        ("0002024001", 2024),
        ("0002025001", 2025),
        ("0002026001", 2026),
    ]
    store = BulkArchiveStore(paths.bulk_archives_root)
    assert store.open("bdc_report") is not None
