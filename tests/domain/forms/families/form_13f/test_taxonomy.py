"""Tests for Form 13F taxonomy specifications."""

from edgar_sec.domain.forms.families.form_13f.taxonomy import (
    FORM13F_INVESTMENT_DISCRETION,
    FORM13F_REPORT_TYPES,
    FORM13F_SUBMISSION_TYPES,
    FORM13F_XML_NAMESPACE,
    FORM13F_XML_SPEC,
)


def test_form13f_taxonomy_codes() -> None:
    """Validate submission types and XML spec."""
    assert "13F-HR" in FORM13F_SUBMISSION_TYPES
    assert "13F-CTR/A" in FORM13F_SUBMISSION_TYPES
    assert "13F HOLDINGS REPORT" in FORM13F_REPORT_TYPES
    assert FORM13F_INVESTMENT_DISCRETION == frozenset({"SOLE", "DFND", "OTR"})
    assert "edgarSubmission" in FORM13F_XML_SPEC.root_tags
    assert "informationTable" in FORM13F_XML_SPEC.root_tags
    assert FORM13F_XML_NAMESPACE in FORM13F_XML_SPEC.namespaces
