"""Tests for form-family collapsing and era banding in selection features."""

from __future__ import annotations

import pytest

from edgar_sec.engine.selection.features import (
    FORM_FAMILY_SUFFIXES,
    era_of,
    form_family,
    form_family_sql,
)
from edgar_sec.engine.selection.policy import EraBand
from edgar_sec.infra.storage.duckdb import connect


FORM_BATTERY = (
    "10-K",
    "10-K/A",
    "10-K_A",
    "10-K405",
    "10-Q",
    "8-K/A",
    "8-K12B",
    "20-F-POS",
    "S-1_A",
    "N-CSR",
    "6-K/A",
    # Multiple suffixes must be collapsed in sequence.
    "10-K/A-POS",
    # Degenerate: nothing but suffixes, so the collapse is empty.
    "/A",
    "MEF",
    "  10-k  ",
    "",
)


def test_form_family_collapses_amendment_suffixes() -> None:
    assert form_family("10-K/A") == "10-K"
    assert form_family("10-K_A") == "10-K"
    assert form_family("20-F-POS") == "20-F"
    assert form_family("8-K/A") == "8-K"
    assert form_family("S-1_A") == "S-1"


def test_form_family_strips_every_known_suffix() -> None:
    """Each suffix the vocabulary declares must actually be collapsible."""
    for suffix in FORM_FAMILY_SUFFIXES:
        assert form_family(f"10-K{suffix}") == "10-K", suffix


def test_form_family_falls_back_to_the_original_when_nothing_remains() -> None:
    assert form_family("/A") == "/A"
    assert form_family("MEF") == "MEF"


def test_form_family_normalizes_case_and_padding() -> None:
    assert form_family("  10-k  ") == "10-K"


def test_form_family_sql_matches_the_python_rule() -> None:
    expression = form_family_sql("f")
    with connect() as con:
        con.execute("CREATE TEMP TABLE forms(f VARCHAR)")
        con.executemany("INSERT INTO forms VALUES (?)", [[f] for f in FORM_BATTERY])
        rows = con.execute(f"SELECT f, {expression} FROM forms").fetchall()

    assert len(rows) == len(FORM_BATTERY)
    mismatches = [
        (raw, sql, form_family(raw))
        for raw, sql in rows
        if sql != form_family(str(raw))
    ]
    assert mismatches == []


def test_form_family_sql_rejects_an_unsafe_column() -> None:
    with pytest.raises(ValueError, match="unsafe SQL column identifier"):
        form_family_sql("f) OR 1=1 --")


def test_era_of_matches_the_first_satisfying_band() -> None:
    bands = [
        EraBand(name="pre_2000", end_year=2000),
        EraBand(name="2000_2010", start_year=2000, end_year=2011),
        EraBand(name="2011_plus", start_year=2011),
    ]
    assert era_of("1998-12-31", bands) == "pre_2000"
    assert era_of("2005-06-15", bands) == "2000_2010"
    assert era_of("2023-01-01", bands) == "2011_plus"


def test_era_of_reports_unknown_rather_than_dropping_the_row() -> None:
    bands = [EraBand(name="modern", start_year=2010)]
    assert era_of(None, bands) == "unknown"
    assert era_of("", bands) == "unknown"
    assert era_of("not-a-date", bands) == "unknown"
    assert era_of("1999-12-31", bands) == "unknown"


def test_era_bands_tile_without_gaps_or_overlap() -> None:
    bands = [
        EraBand(name="a", start_year=1995, end_year=2005),
        EraBand(name="b", start_year=2005, end_year=2011),
    ]
    for year in range(1995, 2011):
        matches = [
            band.name
            for band in bands
            if band.matches(year=year, date_str=f"{year}-06-30")
        ]
        assert matches == [bands[year >= 2005].name]
