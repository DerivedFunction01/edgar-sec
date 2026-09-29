"""Unit and contract tests for edgar_sec.engine.forms.cover.extractors."""

from __future__ import annotations

from edgar_sec.engine.forms.cover.extractors import (
    extract_candidate_ein,
    extract_commission_file_number,
    extract_fiscal_period,
    match_company_name,
    normalize_ein,
)


def test_normalize_ein_and_candidates() -> None:
    assert normalize_ein("12-3456789") == "12-3456789"
    assert normalize_ein("12 3456789") == "12-3456789"
    assert normalize_ein("123456789") == "12-3456789"
    assert normalize_ein("12345") is None
    assert normalize_ein("000012345") is None

    assert (
        extract_candidate_ein("I.R.S. Employer Identification No. 94-2404110")
        == "94-2404110"
    )
    assert extract_candidate_ein("EIN: 942404110") == "94-2404110"


def test_extract_candidate_ein_label_proximity() -> None:
    assert (
        extract_candidate_ein("IRS Employer Identification No. 12-3456789")
        == "12-3456789"
    )
    assert (
        extract_candidate_ein("Employer Identification Number 12 3456789")
        == "12-3456789"
    )
    assert extract_candidate_ein("random text 12-3456789 more text") == "12-3456789"
    assert extract_candidate_ein("no ein here") is None
    assert extract_candidate_ein("partial 12345678") is None


def test_extract_fiscal_period_full_dates() -> None:
    assert (
        extract_fiscal_period("For the fiscal year ended December 31, 2024")
        == "December 31, 2024"
    )
    assert extract_fiscal_period("Fiscal year ended June 30, 2023") == "June 30, 2023"
    assert extract_fiscal_period("period ended 31 December 2022") == "31 December 2022"


def test_extract_fiscal_period_numeric_dates() -> None:
    assert extract_fiscal_period("fiscal year ended 12/31/2024") == "12/31/2024"
    assert extract_fiscal_period("fiscal year ended 12-31-2024") == "12-31-2024"
    # 2-digit year support anchored to filing year
    assert (
        extract_fiscal_period("fiscal year ended 12/31/95", filing_year=1995)
        == "12/31/95"
    )
    assert extract_fiscal_period("fiscal year ended 12/31/95", filing_year=2024) is None


def test_extract_fiscal_period_standalone_year() -> None:
    assert extract_fiscal_period("For the fiscal year ended 2024") == "2024"
    assert extract_fiscal_period("fiscal year ending 2023") == "2023"


def test_extract_fiscal_period_filing_year_guard() -> None:
    assert (
        extract_fiscal_period(
            "For the fiscal year ended December 31, 2024", filing_year=2024
        )
        == "December 31, 2024"
    )
    assert (
        extract_fiscal_period(
            "For the fiscal year ended December 31, 2019", filing_year=2024
        )
        is None
    )


def test_extract_fiscal_period_no_match() -> None:
    assert extract_fiscal_period("some unrelated text") is None
    assert extract_fiscal_period("") is None


def test_company_name_matching_tiers() -> None:
    # Tier 1 Exact
    matched, _, confidence = match_company_name(
        "PLANTRONICS INC /CA/", "Plantronics, Inc."
    )
    assert matched is True
    assert confidence == 1.0

    # Tier 2 Legal Family Stem
    matched, _, confidence = match_company_name("The Viola Group, Inc.", "VIOLA CORP")
    assert matched is True
    assert confidence == 0.95

    # Former Names
    matched, _, confidence = match_company_name(
        "Tesla Motors, Inc.", "TESLA INC", ["TESLA MOTORS INC"]
    )
    assert matched is True
    assert confidence == 1.0


def test_extract_commission_file_number() -> None:
    assert (
        extract_commission_file_number("Commission File Number: 001-35229")
        == "001-35229"
    )
    assert extract_commission_file_number("File Number 033-12345-01") == "033-12345-01"
    assert extract_commission_file_number("No file number here") is None
