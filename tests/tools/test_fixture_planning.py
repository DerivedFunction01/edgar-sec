"""Fixture planning: screens, sharding, and sampling over the catalog."""

from __future__ import annotations

from edgar_sec.tools.fixture_planning import (
    SCREENS,
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
