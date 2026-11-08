"""Verify: reconciled loads pass; population and FSDS closure report."""

from __future__ import annotations

import csv
import zipfile
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


_SUB_HEADER = [
    "adsh",
    "cik",
    "name",
    "sic",
    "countryba",
    "stprba",
    "cityba",
    "zipba",
    "bas1",
    "bas2",
    "baph",
    "countryma",
    "stprma",
    "cityma",
    "zipma",
    "mas1",
    "mas2",
    "countryinc",
    "stprinc",
    "ein",
    "former",
    "changed",
    "afs",
    "wksi",
    "fye",
    "form",
    "period",
    "fy",
    "fp",
    "filed",
    "accepted",
    "prevrpt",
    "detail",
    "instance",
    "nciks",
    "aciks",
]
_PRE_HEADER = [
    "adsh",
    "report",
    "line",
    "stmt",
    "inpth",
    "rfile",
    "tag",
    "version",
    "plabel",
    "negating",
]
_NUM_HEADER = [
    "adsh",
    "tag",
    "version",
    "ddate",
    "qtrs",
    "uom",
    "segments",
    "coreg",
    "value",
    "footnote",
]
_TAG_HEADER = [
    "tag",
    "version",
    "custom",
    "abstract",
    "datatype",
    "iord",
    "crdr",
    "tlabel",
    "doc",
]
_A = "0000320193-23-000106"
_B = "0000789019-23-000001"


def _member(header: list[str], rows: list[dict[str, str]]) -> str:
    lines = ["\t".join(header)]
    lines += ["\t".join(row.get(column, "") for column in header) for row in rows]
    return "\n".join(lines) + "\n"


def _fsds_zip(
    path: Path,
    sub_adshs: list[str],
    num_rows: list[dict[str, str]],
    tag_rows: list[dict[str, str]],
) -> Path:
    # Synthetic subset on the probed headers; the real specimen is pending.
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "sub.txt",
            _member(
                _SUB_HEADER, [{"adsh": adsh, "cik": "320193"} for adsh in sub_adshs]
            ),
        )
        archive.writestr("num.txt", _member(_NUM_HEADER, num_rows))
        archive.writestr("pre.txt", _member(_PRE_HEADER, []))
        archive.writestr("tag.txt", _member(_TAG_HEADER, tag_rows))
        archive.writestr("readme.htm", "<html></html>")
    return path


def _import_fsds(tmp_path: Path, archive: Path) -> object:
    paths = resolve_datasets_paths(tmp_path)
    import_local_archive(
        paths,
        spec_for("fsds"),
        "2009q2",
        archive,
        source_url="https://www.sec.gov/example.zip",
        loaded_at="2026-11-08T00:00:00+00:00",
    )
    return verify_store(paths.store_file)


def test_verify_fsds_closure_reconciles(tmp_path: Path) -> None:
    num_rows = [
        {"adsh": _A, "tag": "Assets", "version": "us-gaap/2023", "value": "1"},
        {"adsh": _B, "tag": "Assets", "version": "us-gaap/2023", "value": "2"},
    ]
    tag_rows = [{"tag": "Assets", "version": "us-gaap/2023", "custom": "0"}]
    archive = _fsds_zip(tmp_path / "fsds.zip", [_A, _B], num_rows, tag_rows)
    result = _import_fsds(tmp_path, archive)
    assert result.ok
    assert len(result.fsds) == 1
    check = result.fsds[0]
    assert check.sub_rows == 2
    assert check.num_accessions == 2
    assert check.num_orphan_accessions == 0
    assert check.sub_without_num == 0
    assert check.num_tag_pairs == check.tag_pairs == 1
    assert check.tag_pair_divergence == 0


def test_verify_fsds_closure_reports_orphans_and_pair_divergence(
    tmp_path: Path,
) -> None:
    orphan = "0000000000-23-999999"
    num_rows = [
        {"adsh": _A, "tag": "Assets", "version": "us-gaap/2023", "value": "1"},
        {"adsh": orphan, "tag": "Ghost", "version": "us-gaap/2023", "value": "2"},
    ]
    tag_rows = [{"tag": "Assets", "version": "us-gaap/2023", "custom": "0"}]
    archive = _fsds_zip(tmp_path / "fsds.zip", [_A], num_rows, tag_rows)
    result = _import_fsds(tmp_path, archive)
    assert not result.ok
    check = result.fsds[0]
    assert check.num_orphan_accessions == 1
    assert check.num_tag_pairs == 2
    assert check.tag_pairs == 1
    assert check.tag_pair_divergence == 1


def test_verify_fsds_empty_vintage_reconciles(tmp_path: Path) -> None:
    archive = _fsds_zip(tmp_path / "fsds.zip", [], [], [])
    result = _import_fsds(tmp_path, archive)
    assert result.ok
    assert result.fsds[0].sub_rows == 0
    assert result.fsds[0].num_accessions == 0


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
