"""Tests for Form N-CEN taxonomy specifications."""

from edgar_sec.domain.forms.families.form_ncen.taxonomy import (
    N_CEN_NAMESPACE,
    N_CEN_SUBMISSION_TYPES,
    N_CEN_XML_SPEC,
)


def test_ncen_taxonomy_codes() -> None:
    """Validate submission types and XML spec."""
    assert N_CEN_SUBMISSION_TYPES == frozenset({"N-CEN", "N-CEN/A"})
    assert "edgarSubmission" in N_CEN_XML_SPEC.root_tags
    assert N_CEN_NAMESPACE in N_CEN_XML_SPEC.namespaces
