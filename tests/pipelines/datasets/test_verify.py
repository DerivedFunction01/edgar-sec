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


_FSDS_SPECIMEN = "datasets/fsds_2009q2_specimen.zip"


def _specimen_member(name: str) -> str:
    with zipfile.ZipFile(fixture_path(_FSDS_SPECIMEN)) as archive:
        return archive.read(name).decode("utf-8")


def _rewrite_specimen(tmp_path: Path, members: dict[str, str]) -> Path:
    target = tmp_path / "fsds.zip"
    with (
        zipfile.ZipFile(fixture_path(_FSDS_SPECIMEN)) as source,
        zipfile.ZipFile(target, "w") as archive,
    ):
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename in members:
                data = members[info.filename].encode("utf-8")
            archive.writestr(info.filename, data)
    return target


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


# Specimen closure, counted from its own members: 22 sub rows over 22
# accessions, 21 num accessions, 1 sub without num, 649 tag pairs a side.
def test_verify_fsds_closure_reconciles(tmp_path: Path) -> None:
    result = _import_fsds(tmp_path, fixture_path(_FSDS_SPECIMEN))
    assert result.ok
    assert len(result.fsds) == 1
    check = result.fsds[0]
    assert check.sub_rows == 22
    assert check.num_accessions == 21
    assert check.num_orphan_accessions == 0
    assert check.sub_without_num == 1
    assert check.num_tag_pairs == check.tag_pairs == 649
    assert check.tag_pair_divergence == 0


def test_verify_fsds_closure_reports_orphans_and_pair_divergence(
    tmp_path: Path,
) -> None:
    num_text = _specimen_member("num.txt")
    lines = num_text.splitlines()
    header = lines[0].split("\t")
    row = lines[1].split("\t")
    row[header.index("adsh")] = "0000000000-09-999999"
    row[header.index("tag")] = "RepointInjectedTag"
    archive = _rewrite_specimen(tmp_path, {"num.txt": num_text + "\t".join(row) + "\n"})
    result = _import_fsds(tmp_path, archive)
    assert not result.ok
    check = result.fsds[0]
    assert check.num_accessions == 22
    assert check.num_orphan_accessions == 1
    assert check.num_tag_pairs == 650
    assert check.tag_pairs == 649
    assert check.tag_pair_divergence == 1


def test_verify_fsds_empty_vintage_reconciles(tmp_path: Path) -> None:
    members = {
        name: _specimen_member(name).splitlines()[0] + "\n"
        for name in ("sub.txt", "num.txt", "pre.txt", "tag.txt")
    }
    result = _import_fsds(tmp_path, _rewrite_specimen(tmp_path, members))
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
