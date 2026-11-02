from edgar_sec.engine.forms.common.dates import (
    external_reference_year,
    format_iso_date,
    is_valid_schema_date_lexeme,
    normalize_iso_date,
    reported_year,
    resolve_reference_year,
)


def test_iso_date_requires_an_anchor_for_two_digit_years() -> None:
    assert normalize_iso_date("10/19/26") is None
    assert normalize_iso_date("10/19/26", reference_year=2026) == "2026-10-19"


def test_iso_date_accepts_day_first_full_dates() -> None:
    assert normalize_iso_date("17 AUG 2011", reference_year=2011) == "2011-08-17"
    assert normalize_iso_date("17-Aug-2011", reference_year=2011) == "2011-08-17"
    assert normalize_iso_date("September 2010", reference_year=2010) is None


def test_reported_year_requires_one_valid_explicit_year() -> None:
    assert reported_year(("Oct 19, 2026", "10/19/26")) == 2026
    assert reported_year(("10/19/26",)) is None
    assert reported_year(("Oct 19, 2026", "Oct 20, 2027")) == 2026


def test_external_report_date_precedes_filing_date_as_year_anchor() -> None:
    assert external_reference_year("2024-12-31", "2025-01-02") == 2024
    assert external_reference_year(None, "2025-01-02") == 2025
    assert resolve_reference_year("2024-12-31", "2025-01-02", ("Oct 1, 2023",)) == 2024
    assert resolve_reference_year(None, None, ("Oct 1, 2023",)) == 2023


def test_xml_date_format_requires_canonical_internal_iso() -> None:
    assert format_iso_date("2026-10-19", month_first=True) == "10-19-2026"
    assert format_iso_date("10/19/26", month_first=True) is None


def test_schema_date_lexeme_accepts_hyphen_and_slash_delimiters() -> None:
    assert is_valid_schema_date_lexeme("2024-09-30", "09/30/2024", month_first=True)
    assert is_valid_schema_date_lexeme("2024-09-30", "09-30-2024", month_first=True)
    assert is_valid_schema_date_lexeme("2026-05-15", "5/15/2026", month_first=True)
    assert not is_valid_schema_date_lexeme("2024-09-30", "2024-09-30", month_first=True)
    assert not is_valid_schema_date_lexeme("2024-09-30", "30/09/2024", month_first=True)
    assert is_valid_schema_date_lexeme("2024-09-30", "2024-09-30", month_first=False)


def test_schema_date_accepts_ordinal_day_of_month_phrases() -> None:
    """Verify ordinal day-of-month clauses normalize to canonical ISO dates."""
    clause = (
        "IN WITNESS WHEREOF, the undersigned has executed this as of this "
        "30th day of November, 2011."
    )
    assert normalize_iso_date(clause) == "2011-11-30"
