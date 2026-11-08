"""Store loads: fixture vintages land DuckDB-side with reconciled counts."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.pipelines.datasets.paths import resolve_datasets_paths
from edgar_sec.pipelines.datasets.specs import spec_for
from edgar_sec.pipelines.datasets.store import (
    VINTAGES_RELATION,
    load_vintage,
    open_store,
)
from tests.support import fixture_path

_SHA = "a" * 64


def _load(tmp_path: Path, set_id: str, fixture: str, vintage: str):
    paths = resolve_datasets_paths(tmp_path)
    con = open_store(paths.store_file)
    try:
        load = load_vintage(
            con,
            spec_for(set_id),
            fixture_path(fixture),
            vintage=vintage,
            archive_sha=_SHA,
            source_url="https://www.sec.gov/example.zip",
            loaded_at="2026-11-08T00:00:00+00:00",
            work_dir=tmp_path / "work",
        )
        vintages = con.execute(
            f"SELECT set_id, vintage FROM {VINTAGES_RELATION}"
        ).fetchall()
    finally:
        con.close()
    return load, vintages


def test_bdc_specimen_loads_core_tables_but_not_soi(tmp_path: Path) -> None:
    load, vintages = _load(
        tmp_path, "bdc", "datasets/bdc_2026_01_specimen.zip", "2026_01"
    )
    relations = {table.relation for table in load.tables}
    assert "bdc_sub" in relations
    assert "bdc_num" in relations
    assert not any("soi" in relation for relation in relations)
    assert all(table.loaded_rows == table.source_rows for table in load.tables)
    assert vintages == [("bdc", "2026_01")]


def test_nmfp_specimen_loads_submission_table(tmp_path: Path) -> None:
    load, _ = _load(
        tmp_path,
        "nmfp",
        "datasets/nmfp_20220808-20220908_specimen.zip",
        "20220808-20220908",
    )
    by_relation = {table.relation: table for table in load.tables}
    assert by_relation["nmfp_submission"].loaded_rows == 358
    assert all(table.loaded_rows == table.source_rows for table in load.tables)


def test_mfrr_specimen_is_the_complete_vintage(tmp_path: Path) -> None:
    load, _ = _load(tmp_path, "mfrr", "datasets/mfrr_2010q4_specimen.zip", "2010q4")
    by_relation = {table.relation: table for table in load.tables}
    assert by_relation["mfrr_sub"].loaded_rows == 2
    assert by_relation["mfrr_num"].loaded_rows == 904


def test_reload_of_one_slice_replaces_it(tmp_path: Path) -> None:
    paths = resolve_datasets_paths(tmp_path)
    con = open_store(paths.store_file)
    try:
        for _ in range(2):
            load = load_vintage(
                con,
                spec_for("mfrr"),
                fixture_path("datasets/mfrr_2010q4_specimen.zip"),
                vintage="2010q4",
                archive_sha=_SHA,
                source_url="https://www.sec.gov/example.zip",
                loaded_at="2026-11-08T00:00:00+00:00",
                work_dir=tmp_path / "work",
            )
        count = con.execute("SELECT count(*) FROM mfrr_sub").fetchone()[0]
    finally:
        con.close()
    assert count == 2
