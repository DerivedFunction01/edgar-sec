"""Unit and contract tests for modular date parsing and healing."""

from __future__ import annotations

import pytest

from defs.text.dates import (
    MONTH_SUFFIX_RE,
    YEAR_IN_TEXT_RE,
    YEAR_TOKEN_RE,
    DateComponents,
    extract_years,
    heal_date_fragments,
    month_name_to_index,
    parse_date,
    parse_numeric_year,
    parse_year_token,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("December 31, 2024", "2024-12-31"),
        ("December 31 2024", "2024-12-31"),
        ("Dec 31, 2024", "2024-12-31"),
        ("Dec. 31, 2024", "2024-12-31"),
        ("31 December 2024", "2024-12-31"),
        ("2024-12-31", "2024-12-31"),
        ("12/31/2024", "2024-12-31"),
        ("12-31-2024", "2024-12-31"),
        ("08 September 2024", "2024-09-08"),
        ("September 08, 2024", "2024-09-08"),
        ("Sept 08, 2024", "2024-09-08"),
        ("2024 December 31", "2024-12-31"),
    ],
)
def test_parse_date_complete(text: str, expected: str) -> None:
    parsed = parse_date(text)
    assert parsed is not None
    assert parsed.iso == expected


@pytest.mark.parametrize(
    "text",
    [
        "February 30, 2024",
        "February 29, 2023",
        "13/31/2024",
        "December 32, 2024",
        "Not a date at all",
        "0000",
    ],
)
def test_parse_date_rejects_invalid(text: str) -> None:
    assert parse_date(text) is None


def test_parse_date_leap_year() -> None:
    assert parse_date("February 29, 2024") is not None
    assert parse_date("February 29, 2025") is None


def test_ordinal_day_suffixes() -> None:
    parsed = parse_date("December 31st, 2024")
    assert parsed is not None
    assert parsed.iso == "2024-12-31"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (["December", "31,", "2024"], ["December 31, 2024"]),
        (["31", "December", "2024"], ["31 December 2024"]),
        (["12/", "31/", "2024"], ["12/31/2024"]),
        (["2024-", "12-", "31"], ["2024-12-31"]),
        (["Dec", "08,", "2024"], ["Dec 08, 2024"]),
    ],
)
def test_heal_date_fragments(text: list[str], expected: list[str]) -> None:
    assert heal_date_fragments(text) == expected


def test_heal_date_fragments_idempotent() -> None:
    once = heal_date_fragments(["December", "31,", "2024"])
    twice = heal_date_fragments(once)
    assert once == twice


def test_heal_date_fragments_protects_non_dates() -> None:
    lines = ["Revenue", "1000000", "Expenses", "500000"]
    assert heal_date_fragments(lines) == lines


def test_month_name_to_index() -> None:
    assert month_name_to_index("January") == 1
    assert month_name_to_index("jan") == 1
    assert month_name_to_index("jan.") == 1
    assert month_name_to_index("Sept") == 9
    assert month_name_to_index("sept.") == 9
    assert month_name_to_index("31st") is None
    assert month_name_to_index("invalid") is None


def test_month_suffix_regex() -> None:
    assert MONTH_SUFFIX_RE.search("ended December")
    assert MONTH_SUFFIX_RE.search("For the fiscal year ended Dec")
    assert not MONTH_SUFFIX_RE.search("December only")


def test_year_token_regex() -> None:
    assert YEAR_TOKEN_RE.match("2024")
    assert not YEAR_TOKEN_RE.match("1899")
    assert not YEAR_TOKEN_RE.match("12345")


def test_year_in_text_regex() -> None:
    matches = YEAR_IN_TEXT_RE.findall("Year 2024 and 2025")
    assert matches == ["2024", "2025"]


def test_parse_year_token() -> None:
    assert parse_year_token("2024") == 2024
    assert parse_year_token("1899") is None
    assert parse_year_token("99") is None


def test_parse_numeric_year_century_expansion() -> None:
    assert parse_numeric_year("24") == 2024
    assert parse_numeric_year("99") == 1999
    assert parse_numeric_year("00") == 2000
    assert parse_numeric_year("1899") is None


def test_extract_years() -> None:
    assert extract_years("Year 2024 and 2025") == [2024, 2025]
    assert extract_years("No years here") == []


def test_date_components_valid() -> None:
    assert DateComponents(2024, 2, 29).valid()
    assert not DateComponents(2023, 2, 29).valid()
