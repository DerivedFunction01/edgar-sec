"""Tests for Form D taxonomy specifications."""

from edgar_sec.domain.forms.families.form_d.taxonomy import (
    FORMD_ENTITY_TYPES,
    FORMD_LIVE_TEST_TYPES,
    FORMD_SUBMISSION_TYPES,
    FORMD_XML_SPEC,
)


def test_formd_taxonomy_codes() -> None:
    """Validate submission types and XML spec."""
    assert "D" in FORMD_SUBMISSION_TYPES
    assert "D/A" in FORMD_SUBMISSION_TYPES
    assert "LIVE" in FORMD_LIVE_TEST_TYPES
    assert "Corporation" in FORMD_ENTITY_TYPES
    assert "edgarSubmission" in FORMD_XML_SPEC.root_tags
