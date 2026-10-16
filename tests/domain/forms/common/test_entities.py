"""Unit tests for domain common entities vocabulary."""

from edgar_sec.domain.forms.common.entities import (
    EXCHANGE_PREFIX_TERMS,
    ISSUER_LABEL_TERMS,
    STREET_ANCHOR_TERMS,
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
    assert "avenue" in STREET_ANCHOR_TERMS
    assert "nasdaq" in EXCHANGE_PREFIX_TERMS
    assert "issuer name" in ISSUER_LABEL_TERMS
