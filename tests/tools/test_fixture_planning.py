"""Fixture planning: screens, sharding, and sampling over the catalog."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.tools.fixture_planning import (
    SCREENS,
    Screen,
    _population,
    _sample,
    _shards,
    screen_from_config,
)


def _record(accession: str, year: int, *, xbrl: bool = True, seed: bool = False):
    return {
        "cik": "0000000001",
        "filer": "Example",
        "accession": accession,
        "form": "8-K/A",
        "filing_date": f"{year}-06-30",
        "period": f"{year}-06-30",
        "is_xbrl": xbrl,
        "is_inline_xbrl": xbrl,
        "primary_document": "doc.htm",
        "archive_url": "https://example.invalid/doc.htm",
        "seed_filer": seed,
        "screen": "8ka-901a",
    }


def test_shards_band_and_block_the_population():
    population = [_record(f"acc-{i}", 2012) for i in range(401)]
    population.append(_record("acc-seed", 2024, seed=True))
    shards = _shards(SCREENS["8ka-901a"], population)
    assert [s["candidates"] for s in shards] == [400, 1, 1]
    assert shards[0]["band"] == "2011-2014"
    assert shards[-1]["seed_candidates"] == 1
    assert shards[0]["estimated_requests"] == 1200


def test_screen_from_config_defaults_and_pinned_forms():
    screen = screen_from_config({"name": "x", "required_item": "9.01"})
    assert (screen.year_start, screen.year_end) == (2011, 2026)
    assert screen.forms is None
    pinned = screen_from_config(
        {
            "name": "x",
            "required_item": "9.01",
            "forms": ["8-K/A"],
            "years": [2020, 2021],
        }
    )
    assert pinned.forms == ("8-K/A",)
    assert (pinned.year_start, pinned.year_end) == (2020, 2021)
    assert screen.require_xbrl is False
    flagged = screen_from_config(
        {"name": "x", "required_item": "9.01", "require_xbrl": True}
    )
    assert flagged.require_xbrl is True


def _filing(accession: str, date: str, *, xbrl: bool) -> dict:
    return {
        "accession_number": accession,
        "form": "8-K/A",
        "filing_date": date,
        "report_date": date,
        "is_xbrl": xbrl,
        "is_inline_xbrl": xbrl,
        "primary_document": "doc.htm",
        "archive_url": "https://example.invalid/doc.htm",
        "items": ["9.01"],
    }


def _write_catalog(tmp_path: Path, filings: list[dict]) -> None:
    filing_type = pa.struct(
        [
            ("accession_number", pa.string()),
            ("form", pa.string()),
            ("filing_date", pa.string()),
            ("report_date", pa.string()),
            ("is_xbrl", pa.bool_()),
            ("is_inline_xbrl", pa.bool_()),
            ("primary_document", pa.string()),
            ("archive_url", pa.string()),
            ("items", pa.list_(pa.string())),
        ]
    )
    schema = pa.schema(
        [
            ("cik", pa.string()),
            ("identity", pa.struct([("name", pa.string())])),
            ("filings", pa.list_(filing_type)),
        ]
    )
    table = pa.Table.from_pylist(
        [{"cik": "0000000001", "identity": {"name": "Example"}, "filings": filings}],
        schema=schema,
    )
    pq.write_table(table, tmp_path / "catalog.parquet")


def test_population_require_xbrl_keeps_only_flagged(tmp_path: Path):
    _write_catalog(
        tmp_path,
        [
            _filing("acc-xbrl", "2020-01-15", xbrl=True),
            _filing("acc-plain", "2021-01-15", xbrl=False),
        ],
    )
    base = {
        "name": "t",
        "required_item": "9.01",
        "phrasings": (),
        "year_start": 2011,
        "year_end": 2026,
    }
    open_rows = _population(Screen(**base), tmp_path)
    assert [r["accession"] for r in open_rows] == ["acc-xbrl", "acc-plain"]
    flagged_rows = _population(Screen(**base, require_xbrl=True), tmp_path)
    assert [r["accession"] for r in flagged_rows] == ["acc-xbrl"]


def test_sample_strides_the_population_deterministically():
    population = [{"accession": f"acc-{i}"} for i in range(1000)]
    taken, info = _sample(population, 10)
    assert info == {"requested": 10, "population": 1000, "taken": 10}
    assert taken[0] is population[0]
    assert taken[-1] is population[900]
    again, _ = _sample(population, 10)
    assert [r["accession"] for r in again] == [r["accession"] for r in taken]
    full, no_info = _sample(population, None)
    assert full is population and no_info is None
