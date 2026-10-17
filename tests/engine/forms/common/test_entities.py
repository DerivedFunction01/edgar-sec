"""Unit tests for engine common entities regexes."""

from edgar_sec.engine.forms.common.entities import (
    CLEAN_TEMPLATE_RE,
    CRD_RE,
    CUSIP_RE,
    IRS_RE,
    RELATIONSHIP_TO_ISSUER_RE,
    SEC_FILE_NUMBER_RE,
    STATE_ZIP_RE,
    STREET_ANCHOR_RE,
    STREET_SUFFIX_RE,
    TICKER_PAREN_RE,
    normalize_exchange_name,
)


def test_state_zip_and_irs_matching():
    """Verify state/zip and IRS tax ID extraction."""
    assert bool(STATE_ZIP_RE.search("New York, NY 10001"))
    assert bool(IRS_RE.search("12-3456789"))
    assert bool(IRS_RE.search("123456789"))


def test_clean_template_and_ticker():
    """Verify template artifact stripping and ticker regex."""
    assert bool(CLEAN_TEMPLATE_RE.search("(Last)"))
    assert bool(STREET_ANCHOR_RE.search("123 Main Street"))
    match = TICKER_PAREN_RE.search("(NASDAQ: AAPL)")
    assert match is not None
    assert match.group(1) == "AAPL"


def test_street_suffix_and_exchange_normalization():
    """Verify exchange normalization and CT state vs Ct suffix disambiguation."""
    assert normalize_exchange_name("Traded on NASDQ") == "NASDAQ"
    assert normalize_exchange_name("Listed on NYSE") == "NYSE"
    assert normalize_exchange_name("Unknown Exchange") is None

    matches = list(STREET_SUFFIX_RE.finditer("100 Main Street, Hartford, CT 06103"))
    assert len(matches) == 1
    assert matches[0].group(0).lower() == "street"

    court_matches = list(STREET_SUFFIX_RE.finditer("15 Maple Ct, Hartford, CT 06103"))
    assert len(court_matches) == 1
    assert court_matches[0].group(0).lower() == "ct"


def test_identifiers_and_relationships():
    """Verify SEC file numbers, CUSIP, CRD, and relationship roles."""
    assert bool(SEC_FILE_NUMBER_RE.search("001-12345"))
    assert bool(SEC_FILE_NUMBER_RE.search("028-00500"))
    assert bool(CUSIP_RE.search("037833100"))
    assert bool(CRD_RE.search("123456"))
    assert bool(RELATIONSHIP_TO_ISSUER_RE.search("Officer (give title below)"))
    assert bool(RELATIONSHIP_TO_ISSUER_RE.search("10% Stockholder"))
