"""Tests for Form N-MFP taxonomy specifications."""

from edgar_sec.domain.forms.families.form_nmfp.taxonomy import (
    N_MFP3_NAMESPACE,
    N_MFP_GENERATION_BY_NAMESPACE,
    N_MFP_SUBMISSION_TYPES,
    N_MFP_XML_SPEC,
)


def test_nmfp_taxonomy_codes() -> None:
    """Validate generation submission types, namespaces, and XML spec."""
    assert "N-MFP" in N_MFP_SUBMISSION_TYPES
    assert "N-MFP2/A" in N_MFP_SUBMISSION_TYPES
    assert "N-MFP3" in N_MFP_SUBMISSION_TYPES
    assert N_MFP_GENERATION_BY_NAMESPACE[N_MFP3_NAMESPACE] == 3
    assert "edgarSubmission" in N_MFP_XML_SPEC.root_tags
    assert N_MFP3_NAMESPACE in N_MFP_XML_SPEC.namespaces
