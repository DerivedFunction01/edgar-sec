"""Offline tests for the fixture-candidate gathering tool."""

from __future__ import annotations

import json
from pathlib import Path

from edgar_sec.tools.fixture_candidates import (
    SCREENS,
    _instance_name,
    _sample,
    _shards,
    build_registry,
    count_facts,
    load_config,
    screen_from_config,
)

_INLINE = (
    b'<html><ix:nonNumeric name="us-gaap:Revenues" contextRef="c1">5</ix:nonNumeric>'
    b'<ix:nonFraction name="us-gaap:Assets" contextRef="c1">7</ix:nonFraction>'
    b'<ix:nonNumeric name="dei:EntityRegistrantName" contextRef="c1">X</ix:nonNumeric>'
    b'<ix:nonNumeric name="srt:ProductOrServiceAxis" contextRef="c1">z</ix:nonNumeric></html>'
)
_INSTANCE = (
    b'<xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance">'
    b'<xbrli:context id="c1"/><us-gaap:Revenues>5</us-gaap:Revenues>'
    b"<us-gaap:Assets>7</us-gaap:Assets><dei:Cover>1</dei:Cover></xbrl>"
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


def test_count_facts_inline_buckets_by_prefix():
    counts = count_facts(_INLINE, inline=True)
    assert counts["total_facts"] == 4
    assert counts["us_gaap_facts"] == 2
    assert counts["dei_facts"] == 1


def test_count_facts_instance_skips_structural_prefixes():
    counts = count_facts(_INSTANCE, inline=False)
    assert counts["total_facts"] == 3
    assert counts["us_gaap_facts"] == 2
    assert counts["dei_facts"] == 1


def test_instance_name_skips_linkbases():
    names = ["a.xsd", "a_lab.xml", "a_pre.xml", "a.xml", "doc.htm"]
    assert _instance_name(names, "doc.htm", inline=False) == "a.xml"
    assert _instance_name(["a.xsd"], "doc.htm", inline=False) is None


def test_instance_name_prefers_extracted_instance_for_inline():
    names = ["doc.htm", "doc_htm.xml", "a.xsd"]
    assert _instance_name(names, "doc.htm", inline=True) == "doc_htm.xml"
    assert _instance_name(["doc.htm"], "doc.htm", inline=True) == "doc.htm"


def test_count_facts_dedupes_identical_facts():
    payload = (
        b'<xbrl><us-gaap:Revenues contextRef="c1">5</us-gaap:Revenues>'
        b'<us-gaap:Revenues contextRef="c1">5</us-gaap:Revenues>'
        b'<us-gaap:Revenues contextRef="c2">5</us-gaap:Revenues>'
        b'<xbrldi:explicitMember dimension="d">m</xbrldi:explicitMember></xbrl>'
    )
    counts = count_facts(payload, inline=False)
    assert counts["total_facts"] == 2
    assert counts["us_gaap_facts"] == 2


def test_shards_band_and_block_the_population():
    population = [_record(f"acc-{i}", 2012) for i in range(401)]
    population.append(_record("acc-seed", 2024, seed=True))
    shards = _shards(SCREENS["8ka-901a"], population)
    assert [s["candidates"] for s in shards] == [400, 1, 1]
    assert shards[0]["band"] == "2011-2014"
    assert shards[-1]["seed_candidates"] == 1
    assert shards[0]["estimated_requests"] == 1200


def test_registry_filters_floor_and_ranks_seed_first(tmp_path: Path):
    checkpoint = tmp_path / "checkpoints"
    checkpoint.mkdir()
    rows = [
        {
            **_record("acc-plain", 2024),
            "ex101_present": True,
            "total_facts": 900,
            "us_gaap_facts": 800,
            "dei_facts": 40,
            "phrasing_matches": [],
        },
        {
            **_record("acc-seed", 2024, seed=True),
            "ex101_present": True,
            "total_facts": 300,
            "us_gaap_facts": 250,
            "dei_facts": 40,
            "phrasing_matches": [],
        },
        {
            **_record("acc-thin", 2024),
            "ex101_present": True,
            "total_facts": 60,
            "us_gaap_facts": 50,
            "dei_facts": 10,
            "phrasing_matches": [],
        },
    ]
    (checkpoint / "s.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    registry = build_registry(tmp_path, tmp_path / "out.json", screen_name="8ka-901a")
    assert [r["accession"] for r in registry["candidates"]] == [
        "acc-seed",
        "acc-plain",
    ]
    assert registry["scored_candidates"] == 3


def _write_checkpoint(tmp_path: Path, rows: list[dict]) -> None:
    checkpoint = tmp_path / "checkpoints"
    checkpoint.mkdir(exist_ok=True)
    (checkpoint / "s.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )


def test_registry_without_seed_preference_ranks_by_substance(tmp_path: Path):
    rows = [
        {
            **_record("acc-seed", 2024, seed=True),
            "ex101_present": True,
            "total_facts": 300,
            "us_gaap_facts": 250,
            "dei_facts": 40,
            "phrasing_matches": [],
        },
        {
            **_record("acc-plain", 2024),
            "ex101_present": True,
            "total_facts": 900,
            "us_gaap_facts": 800,
            "dei_facts": 40,
            "phrasing_matches": [],
        },
    ]
    _write_checkpoint(tmp_path, rows)
    registry = build_registry(
        tmp_path,
        tmp_path / "out.json",
        screen_name="8ka-901a",
        prefer_seed=False,
    )
    assert [r["accession"] for r in registry["candidates"]] == [
        "acc-plain",
        "acc-seed",
    ]
    assert registry["seed_filer_preference"] is False


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


def test_load_config_fills_defaults(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"screens": [{"name": "x", "required_item": "9.01"}]}),
        encoding="utf-8",
    )
    config = load_config(path)
    assert config["sample_size"] is None
    assert config["floor_us_gaap_facts"] == 200
    assert config["seed_filer_preference"] is True
    assert config["outputs"]["registry"] == "fixture-candidates-{screen}.json"


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
