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


def test_shared_entity_regexes_and_morphology():
    """Verify shared organization, officer title, and noise patterns."""
    from edgar_sec.engine.forms.common.entities import (
        FILLER_RUN_RE,
        OFFICER_TITLE_BOUNDARY_RE,
        ORGANIZATION_SUFFIX_RE,
        PHONE_NUMBER_RE,
        SSN_REDACTION_MASK_RE,
        TRAILING_FOOTNOTE_RE,
        is_street_address_value,
        is_valid_entity_name,
        sanitize_document_noise,
        strip_footnote_markers,
    )

    assert bool(ORGANIZATION_SUFFIX_RE.search("Acme Holdings Inc."))
    assert bool(ORGANIZATION_SUFFIX_RE.search("Volaris Trust"))
    assert bool(OFFICER_TITLE_BOUNDARY_RE.search("Officer"))
    assert bool(OFFICER_TITLE_BOUNDARY_RE.search("Chief Executive Officer"))
    assert bool(SSN_REDACTION_MASK_RE.match("###-##-####"))
    assert bool(PHONE_NUMBER_RE.search("(212) 555-1234"))
    assert bool(FILLER_RUN_RE.search("____"))
    assert bool(TRAILING_FOOTNOTE_RE.search("John Doe[1]"))

    assert is_street_address_value("345 Park Avenue, 41st Floor")
    assert is_street_address_value("P.O. Box 1234")
    assert is_street_address_value("Baltimore, MD 21202")
    assert not is_street_address_value("Stephen L. Way")
    assert not is_street_address_value("Dr. Patrick Yeramian")
    assert not is_street_address_value("Kings Road Investments Ltd.")

    assert is_valid_entity_name("Bioenvision, Inc.")
    assert is_valid_entity_name("The 2006 MRG/CPG Volaris Trust")
    assert not is_valid_entity_name("USA")
    assert not is_valid_entity_name("12345")

    assert sanitize_document_noise("|  John Doe  ____ |") == "John Doe"
    assert strip_footnote_markers("John Doe [1]") == "John Doe"
    assert strip_footnote_markers("Acme Corp.*") == "Acme Corp."
