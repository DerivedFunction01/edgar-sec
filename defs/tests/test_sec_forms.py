"""Contract tests for defs.sec_forms."""

from __future__ import annotations

from defs.sec_forms import ConceptPattern
from defs.sec_forms.cover.extractors import (
    extract_candidate_ein,
    extract_fiscal_period,
    match_company_name,
    normalize_ein,
)
from defs.sec_forms.cover.vocabulary import (
    ADDRESS_RE,
    COMMISSION_FILE_RE,
    COVER_LABELS,
    IRS_EIN_RE,
    REGISTRANT_NAME_RE,
    SECURITIES_12B_RE,
    STATE_INCORPORATION_RE,
    TELEPHONE_RE,
    ZIP_RE,
)


def test_concept_pattern_compilation_and_bow() -> None:
    cp = ConceptPattern(
        "ein_test", (r"employer\s+identification\s+no\.?", r"i\.?r\.?s\.?\s+ein")
    )
    assert "employer" in cp.tokens
    assert "identification" in cp.tokens
    assert cp.search("Employer Identification No. 12-3456789") is not None
    assert cp.match_score("employer identification number") > 0.4


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

    # Negative Control
    matched, _, confidence = match_company_name("Microsoft Corporation", "APPLE INC")
    assert matched is False
    assert confidence == 0.0


def test_cover_label_matchers_match_bare_forms() -> None:
    assert STATE_INCORPORATION_RE.search("State of Incorporation")
    assert IRS_EIN_RE.search("I.R.S. Employer Identification No.")
    assert ADDRESS_RE.search("Address of principal executive offices")
    assert ZIP_RE.search("Zip Code")
    assert TELEPHONE_RE.search("Telephone number, including area code")
    assert REGISTRANT_NAME_RE.search(
        "Exact name of registrant as specified in its charter"
    )
    assert COMMISSION_FILE_RE.search("Commission File Number")
    assert SECURITIES_12B_RE.search("Title of each class")


def test_cover_label_matchers_match_parenthesized_forms() -> None:
    assert STATE_INCORPORATION_RE.search(
        "(State or other jurisdiction of incorporation or organization)"
    )
    assert IRS_EIN_RE.search("(I.R.S. Employer Identification No.)")
    assert ADDRESS_RE.search("(Address of principal executive offices)")
    assert ZIP_RE.search("(Zip Code)")
    assert COMMISSION_FILE_RE.search("(Commission File Number)")


def test_cover_label_matchers_longest_first() -> None:
    match = STATE_INCORPORATION_RE.search("State of Incorporation")
    assert match is not None
    assert match.group() == "State of Incorporation"
    match = IRS_EIN_RE.search("IRS Employer Identification No.")
    assert match is not None
    assert match.group() == "IRS Employer Identification No."


def test_cover_label_matchers_do_not_match_unrelated_text() -> None:
    assert not STATE_INCORPORATION_RE.search("state of the art technology")
    assert not IRS_EIN_RE.search("IRS forms and instructions")
    assert not ADDRESS_RE.search("address line 2")
    assert not SECURITIES_12B_RE.search("class of securities")
    assert not REGISTRANT_NAME_RE.search("name of the company")


def test_cover_labels_registry_complete() -> None:
    expected_keys = {
        "state_of_incorporation",
        "irs_ein",
        "principal_address",
        "zip_code",
        "telephone",
        "registrant_name",
        "commission_file_number",
        "securities_12b",
    }
    assert set(COVER_LABELS.keys()) == expected_keys
    for key, labels in COVER_LABELS.items():
        assert len(labels) > 0, f"{key} must have at least one label"
        for label in labels:
            assert label.strip() == label, f"{key} label has extra whitespace"
