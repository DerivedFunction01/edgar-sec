"""Unit and contract tests for modular date parsing and healing."""

from __future__ import annotations

import pytest

from defs.text.dates import (
    MONTH_SUFFIX_RE,
    YEAR_IN_TEXT_RE,
    YEAR_TOKEN_RE,
    DateComponents,
    expand_2digit_year,
    extract_years,
    heal_date_fragments,
    is_valid_year,
    is_year_token,
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


def test_heal_date_fragments_preserves_prose_with_embedded_date() -> None:
    lines = [
        "[X] ANNUAL REPORT PURSUANT TO SECTION 13 OR 15(d)",
        "For the fiscal year ended December 31, 2024",
    ]
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


def test_expand_2digit_year() -> None:
    # Default anchor (system year ~2026, window [1946..2046])
    assert expand_2digit_year(24) == 2024
    assert expand_2digit_year(99) == 1999
    assert expand_2digit_year(0) == 2000
    assert expand_2digit_year(2024) == 2024

    # Historical anchor: 1998 filing (window [1918..2018])
    assert expand_2digit_year(95, reference_year=1998) == 1995
    assert expand_2digit_year(98, reference_year=1998) == 1998
    assert expand_2digit_year(1, reference_year=1998) == 2001
    assert expand_2digit_year(20, reference_year=1998) == 1920

    # Distant future anchor: 2105 filing (window [2025..2125])
    assert expand_2digit_year(5, reference_year=2105) == 2105
    assert expand_2digit_year(95, reference_year=2105) == 2095
    assert expand_2digit_year(24, reference_year=2105) == 2124


def test_parse_numeric_year_century_expansion() -> None:
    assert parse_numeric_year("24") == 2024
    assert parse_numeric_year("99") == 1999
    assert parse_numeric_year("00") == 2000
    assert parse_numeric_year("1899") is None
    # With historical anchor
    assert parse_numeric_year("95", reference_year=1998) == 1995
    assert parse_numeric_year("01", reference_year=1998) == 2001


def test_extract_years() -> None:
    assert extract_years("Year 2024 and 2025") == [2024, 2025]
    assert extract_years("No years here") == []
    # 2-digit years with historical anchor
    assert extract_years("Fiscal '95, '98, and '01", reference_year=1998) == [
        1995,
        1998,
        2001,
    ]


def test_date_components_valid() -> None:
    assert DateComponents(2024, 2, 29).valid()
    assert not DateComponents(2023, 2, 29).valid()


def test_is_valid_year() -> None:
    assert is_valid_year(1900)
    assert is_valid_year(2026)
    assert is_valid_year(2100)
    assert not is_valid_year(1899)
    assert not is_valid_year(3500)
    # Test custom future ranges
    assert is_valid_year(2150, valid_range=(1900, 2200))
    assert not is_valid_year(2250, valid_range=(1900, 2200))


def test_is_year_token() -> None:
    assert is_year_token("2024")
    assert is_year_token("1999")
    assert is_year_token("2100")
    assert is_year_token(" 2025 ")
    assert not is_year_token("1899")
    assert not is_year_token("99")
    assert not is_year_token("20245")
    assert not is_year_token("abcd")
    assert not is_year_token("$1000")
