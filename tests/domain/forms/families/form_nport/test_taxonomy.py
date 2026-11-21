"""Tests for Form N-PORT taxonomy specifications."""

from edgar_sec.domain.forms.families.form_nport.taxonomy import (
    NPORT_NAMESPACE,
    NPORT_PAYOFF_PROFILES,
    NPORT_SUBMISSION_TYPES,
    NPORT_XML_SPEC,
)


def test_nport_taxonomy_codes() -> None:
    """Validate submission types and XML spec."""
    assert "NPORT-P" in NPORT_SUBMISSION_TYPES
    assert "NPORT-EX/A" in NPORT_SUBMISSION_TYPES
    assert NPORT_PAYOFF_PROFILES == frozenset({"Long", "Short", "N/A"})
    assert "edgarSubmission" in NPORT_XML_SPEC.root_tags
    assert NPORT_NAMESPACE in NPORT_XML_SPEC.namespaces
