"""Tests for Form N-PX taxonomy specifications."""

from edgar_sec.domain.forms.families.form_npx.taxonomy import (
    N_PX_NAMESPACE,
    N_PX_REGISTRANT_TYPES,
    N_PX_SUBMISSION_TYPES,
    N_PX_VOTE_NAMESPACE,
    N_PX_XML_SPEC,
)


def test_npx_taxonomy_codes() -> None:
    """Validate submission types, roots, and XML spec."""
    assert "N-PX" in N_PX_SUBMISSION_TYPES
    assert "N-PX CTR/A" in N_PX_SUBMISSION_TYPES
    assert N_PX_REGISTRANT_TYPES == frozenset({"IM", "RMIC"})
    assert "edgarSubmission" in N_PX_XML_SPEC.root_tags
    assert "proxyVoteTable" in N_PX_XML_SPEC.root_tags
    assert N_PX_NAMESPACE in N_PX_XML_SPEC.namespaces
    assert N_PX_VOTE_NAMESPACE in N_PX_XML_SPEC.namespaces
