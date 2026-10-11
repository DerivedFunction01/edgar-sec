"""Tests for S10 role assessment data contract."""

from __future__ import annotations

from edgar_sec.domain.forms.common.exhibits import (
    DocumentRoleAssessment,
    EvidenceSpan,
    ExhibitIdentity,
)


def test_evidence_span_creation():
    """Evidence spans store character offsets."""
    span = EvidenceSpan(signal_id="sig1", start_char=10, end_char=50)
    assert span.signal_id == "sig1"
    assert span.start_char == 10
    assert span.end_char == 50


def test_document_role_assessment_required_fields():
    """All required fields must be provided."""
    # Should succeed with minimal required fields and sensible defaults
    assessment = DocumentRoleAssessment(
        expected_role="exhibit",
        expected_type="Exhibit 10.1",
        filing_form="10-K",
        expected_identity=ExhibitIdentity(authority_id="SEC", code="EX-10.1"),
        observed_kind="exhibit",
        observed_identity=ExhibitIdentity(authority_id="SEC", code="EX-10.1"),
        disposition="consistent",
        evaluator_quality="proposed",
        profile_id="default",
        profile_version="v1",
    )
    assert assessment.schema_version == 1
    assert assessment.evaluator_version == "v1"
    assert assessment.supporting_evidence == ()
    assert assessment.contradicting_evidence == ()
    assert assessment.diagnostic_code is None


def test_document_role_assessment_disposition_with_diagnostic():
    """A diagnostic code is required when disposition is possible_role_mismatch."""
    assessment = DocumentRoleAssessment(
        expected_role="primary",
        expected_type="Form 10-K",
        filing_form="10-K",
        expected_identity="10-K",
        observed_kind="exhibit",
        observed_identity=None,
        disposition="possible_role_mismatch",
        diagnostic_code="form_mismatch",
        evaluator_quality="source_supported",
        profile_id="default",
        profile_version="v1",
    )
    assert assessment.diagnostic_code == "form_mismatch"


def test_document_role_assessment_pack_identity():
    """pack_id and pack_version must be provided together when present."""
    # Without pack_id, pack_version should be None
    assessment = DocumentRoleAssessment(
        expected_role="exhibit",
        expected_type="Exhibit 10.1",
        filing_form="10-K",
        expected_identity=ExhibitIdentity(authority_id="SEC", code="EX-10.1"),
        observed_kind="exhibit",
        observed_identity=ExhibitIdentity(authority_id="SEC", code="EX-10.1"),
        disposition="consistent",
        evaluator_quality="proposed",
        profile_id="default",
        profile_version="v1",
    )
    assert assessment.pack_id is None
    assert assessment.pack_version is None
