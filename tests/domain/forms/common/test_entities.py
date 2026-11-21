"""Unit tests for domain common entities vocabulary."""

from edgar_sec.domain.forms.common.entities import (
    CANONICAL_EXCHANGE_NAMES,
    ENTITY_NUMERIC_EXCEPTIONS,
    EXCHANGE_ALIASES,
    EXCHANGE_PREFIX_TERMS,
    FOOTNOTE_PREFIX_TERMS,
    INSTRUCTION_SIGNATURE_PHRASES,
    ISSUER_LABEL_TERMS,
    OFFICER_TITLE_TERMS,
    PHONE_LABEL_TERMS,
    PII_MASK_TERMS,
    RELATIONSHIP_TO_ISSUER_TERMS,
    SECONDARY_UNIT_DESIGNATORS,
    SEC_FILE_NUMBER_PREFIXES,
    STREET_ANCHOR_TERMS,
    STREET_TYPE_SUFFIXES,
    TABULAR_STOPWORDS,
    TEMPLATE_LABELS,
)


def test_template_labels():
    """Verify presence of core template label fields."""
    assert "Last" in TEMPLATE_LABELS
    assert "First" in TEMPLATE_LABELS
    assert "Street" in TEMPLATE_LABELS


def test_street_anchor_and_exchange_terms():
    """Verify street anchors and major stock exchange terms."""
    assert "street" in STREET_ANCHOR_TERMS
    assert "court" in STREET_TYPE_SUFFIXES
    assert "suite" in SECONDARY_UNIT_DESIGNATORS
    assert "level" in SECONDARY_UNIT_DESIGNATORS
    assert "NYSE" in CANONICAL_EXCHANGE_NAMES
    assert EXCHANGE_ALIASES["NASDQ"] == "NASDAQ"
    assert "the" in TABULAR_STOPWORDS
    assert any("whose account" in p for p in INSTRUCTION_SIGNATURE_PHRASES)
    assert "nasdaq" in EXCHANGE_PREFIX_TERMS
    assert "issuer name" in ISSUER_LABEL_TERMS


def test_relationships_and_sec_file_prefixes():
    """Verify relationship roles and SEC file number prefixes."""
    assert "director" in RELATIONSHIP_TO_ISSUER_TERMS
    assert "10% owner" in RELATIONSHIP_TO_ISSUER_TERMS
    assert "001" in SEC_FILE_NUMBER_PREFIXES
    assert "028" in SEC_FILE_NUMBER_PREFIXES


def test_shared_entity_vocabularies():
    """Verify shared PII, phone, title, footnote, and entity exceptions."""
    assert "###-##-####" in PII_MASK_TERMS
    assert "telephone" in PHONE_LABEL_TERMS
    assert "chief executive officer" in OFFICER_TITLE_TERMS
    assert "see footnote" in FOOTNOTE_PREFIX_TERMS
    assert "401(k)" in ENTITY_NUMERIC_EXCEPTIONS
