"""Unit and contract tests for edgar_sec.foundation.text.dates."""

from __future__ import annotations

from edgar_sec.foundation.text.dates import (
    MONTH_NAME_RE,
    MONTH_NAMES,
    RE_FULL_DATE,
    YEAR_IN_TEXT_RE,
    YEAR_TOKEN_RE,
    expand_2digit_year,
    is_valid_year,
    is_year_token,
)


def test_month_names() -> None:
    assert len(MONTH_NAMES) == 12
    assert "january" in MONTH_NAMES
    assert "december" in MONTH_NAMES
    assert MONTH_NAME_RE.match("January") is not None
    assert MONTH_NAME_RE.match("feb.") is not None
    assert MONTH_NAME_RE.match("sept") is not None
    assert MONTH_NAME_RE.match("holiday") is None


def test_year_regex_and_validation() -> None:
    assert YEAR_TOKEN_RE.match("2024") is not None
    assert YEAR_TOKEN_RE.match("1998") is not None
    assert YEAR_TOKEN_RE.match("1899") is None
    assert is_valid_year(2024)
    assert is_valid_year(1998)
    assert not is_valid_year(1850)
    assert is_year_token("2024")
    assert is_year_token("  1998  ")
    assert not is_year_token("202")
    assert not is_year_token("abcd")


def test_full_date_regex() -> None:
    text = "For the year ended December 31, 2024, our revenue grew."
    m = RE_FULL_DATE.search(text)
    assert m is not None
    assert m.group(0) == "December 31, 2024"

    text2 = "As of March 15 2023"
    m2 = RE_FULL_DATE.search(text2)
    assert m2 is not None
    assert m2.group(0) == "March 15 2023"


def test_year_in_text_regex() -> None:
    years = YEAR_IN_TEXT_RE.findall("In 2020 and 2021, compared to 2022.")
    assert years == ["2020", "2021", "2022"]


def test_expand_2digit_year() -> None:
    assert expand_2digit_year(24) == 2024
    assert expand_2digit_year(99) == 1999
    assert expand_2digit_year(0) == 2000
    assert expand_2digit_year(2024) == 2024

    # Historical anchor: 1998 filing (window [1918..2017])
    assert expand_2digit_year(95, reference_year=1998) == 1995
    assert expand_2digit_year(98, reference_year=1998) == 1998
    assert expand_2digit_year(1, reference_year=1998) == 2001
    assert expand_2digit_year(20, reference_year=1998) == 1920

    # Distant future anchor: 2105 filing (window [2025..2124])
    assert expand_2digit_year(5, reference_year=2105) == 2105
    assert expand_2digit_year(95, reference_year=2105) == 2095
    assert expand_2digit_year(24, reference_year=2105) == 2124

    # Explicit century pivot
    assert expand_2digit_year(79, reference_year=2026, century_pivot=80) == 2079
    assert expand_2digit_year(80, reference_year=2026, century_pivot=80) == 1980


def test_parse_numeric_year() -> None:
    from edgar_sec.foundation.text.dates import parse_numeric_year

    assert parse_numeric_year("24") == 2024
    assert parse_numeric_year("99") == 1999
    assert parse_numeric_year("00") == 2000
    assert parse_numeric_year("1899") is None
    assert parse_numeric_year("95", reference_year=1998) == 1995
    assert parse_numeric_year("01", reference_year=1998) == 2001


def test_extract_years() -> None:
    from edgar_sec.foundation.text.dates import extract_years

    assert extract_years("Year 2024 and 2025") == [2024, 2025]
    assert extract_years("No years here") == []
    # 2-digit years with historical anchor
    assert extract_years("Fiscal '95, '98, and '01", reference_year=1998) == [
        1995,
        1998,
        2001,
    ]
    # Date extraction of 2-digit years (12/31/95)
    assert extract_years("Ended 12/31/95 and 12/31/98", reference_year=1998) == [
        1995,
        1998,
    ]


def test_contains_date() -> None:
    from edgar_sec.foundation.text.dates import contains_date

    assert contains_date("December 31, 2024")
    assert contains_date("2024-12-31")
    assert not contains_date("12/31/95")  # strict mode
    assert contains_date("12/31/95", include_partial=True)
    assert contains_date("Dec 95", include_partial=True)
    assert not contains_date("Random text", include_partial=True)


def test_table_year_patterns() -> None:
    from edgar_sec.foundation.text.dates import (
        COLUMN_YEAR_ROW_RE,
        MONTH_SUFFIX_RE,
        PERIOD_SUBHEADING_RE,
    )

    assert MONTH_SUFFIX_RE.search("ended December") is not None
    assert MONTH_SUFFIX_RE.search("For the fiscal year ended Dec") is not None
    assert MONTH_SUFFIX_RE.search("December only") is None

    assert COLUMN_YEAR_ROW_RE.match("   2024       2023       2022   ") is not None
    assert COLUMN_YEAR_ROW_RE.match("   Q1 2024   Q1 2023   ") is not None

    assert (
        PERIOD_SUBHEADING_RE.match("Three months ended December 31, 2024:") is not None
        or PERIOD_SUBHEADING_RE.match("Three months ended 2024:") is not None
    )


def test_heal_date_fragments() -> None:
    from edgar_sec.foundation.text.dates import heal_date_fragments

    assert heal_date_fragments(["December", "31,", "2024"]) == ["December 31, 2024"]
    assert heal_date_fragments(["Dec", "08,", "2024"]) == ["Dec 08, 2024"]


def test_heal_date_fragments_idempotent() -> None:
    from edgar_sec.foundation.text.dates import heal_date_fragments

    once = heal_date_fragments(["December", "31,", "2024"])
    twice = heal_date_fragments(once)
    assert once == twice


def test_heal_date_fragments_protects_non_dates() -> None:
    from edgar_sec.foundation.text.dates import heal_date_fragments

    lines = ["Revenue", "1000000", "Expenses", "500000"]
    assert heal_date_fragments(lines) == lines


def test_heal_date_fragments_preserves_prose_with_embedded_date() -> None:
    from edgar_sec.foundation.text.dates import heal_date_fragments

    lines = [
        "[X] ANNUAL REPORT PURSUANT TO SECTION 13 OR 15(d)",
        "For the fiscal year ended December 31, 2024",
    ]
    assert heal_date_fragments(lines) == lines
