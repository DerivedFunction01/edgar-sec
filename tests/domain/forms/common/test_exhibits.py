"""Tests for S10 role assessment data contract."""

from __future__ import annotations

from edgar_sec.domain.forms.common.exhibits import (
    CoverageEntry,
    DocumentRoleAssessment,
    EvidenceSpan,
    ExhibitAssessmentProfile,
    ExhibitIdentity,
    ScheduleIdentity,
    SourceRef,
)


def test_evidence_span_creation():
    """Evidence spans store character offsets."""
    span = EvidenceSpan(signal_id="sig1", start_char=10, end_char=50)
    assert span.signal_id == "sig1"
    assert span.start_char == 10
    assert span.end_char == 50


def test_schedule_identity():
    """Schedule identity stores schedule identifier."""
    schedule = ScheduleIdentity(schedule="14A")
    assert schedule.schedule == "14A"


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


def test_document_role_assessment_schedule_role():
    """DocumentRoleAssessment supports schedule role and identity."""
    assessment = DocumentRoleAssessment(
        expected_role="schedule",
        expected_type="Schedule 14A",
        filing_form="10-K",
        expected_identity=ScheduleIdentity(schedule="14A"),
        observed_kind="schedule",
        observed_identity=ScheduleIdentity(schedule="14A"),
        disposition="consistent",
        evaluator_quality="proposed",
        profile_id="default",
        profile_version="v1",
    )
    assert assessment.expected_role == "schedule"
    assert isinstance(assessment.expected_identity, ScheduleIdentity)


def test_document_role_assessment_observed_kind_variants():
    """All observed_kind literals are valid."""
    for kind in [
        "primary_report",
        "exhibit",
        "schedule",
        "structured_data",
        "paper_stub",
        "unknown",
    ]:
        assessment = DocumentRoleAssessment(
            expected_role="primary",
            expected_type="Form 10-K",
            filing_form="10-K",
            expected_identity="10-K",
            observed_kind=kind,
            observed_identity=None,
            disposition="insufficient_evidence",
            evaluator_quality="proposed",
            profile_id="default",
            profile_version="v1",
        )
        assert assessment.observed_kind == kind


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


def test_document_role_assessment_suspected_misfiled_schedule():
    """suspected_misfiled_schedule is a valid diagnostic code."""
    assessment = DocumentRoleAssessment(
        expected_role="primary",
        expected_type="Form 10-K",
        filing_form="10-K",
        expected_identity="10-K",
        observed_kind="schedule",
        observed_identity=ScheduleIdentity(schedule="14A"),
        disposition="possible_role_mismatch",
        diagnostic_code="suspected_misfiled_schedule",
        evaluator_quality="proposed",
        profile_id="default",
        profile_version="v1",
    )
    assert assessment.diagnostic_code == "suspected_misfiled_schedule"


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


def test_source_ref():
    """SourceRef stores citation information."""
    ref = SourceRef(
        source_path="edgar_sec/domain/forms/common/exhibits.py",
        section_or_lines="1-100",
        note="D0 contract definition",
    )
    assert ref.source_path == "edgar_sec/domain/forms/common/exhibits.py"
    assert ref.section_or_lines == "1-100"
    assert ref.note == "D0 contract definition"


def test_coverage_entry():
    """CoverageEntry stores authority-qualified code ledger entry."""
    entry = CoverageEntry(
        authority_id="SEC",
        code="EX-10.1",
        title="Material Contract",
        coverage_status="candidate",
        source_refs=(
            SourceRef(source_path="docs/exhibits.md", section_or_lines="10-20"),
        ),
        pack_id="test_pack",
        evaluator_quality="proposed",
    )
    assert entry.authority_id == "SEC"
    assert entry.code == "EX-10.1"
    assert entry.coverage_status == "candidate"
    assert entry.pack_id == "test_pack"


def test_exhibit_assessment_profile():
    """ExhibitAssessmentProfile stores declarative profile."""
    profile = ExhibitAssessmentProfile(
        profile_id="default",
        version="v1",
        authority_id="SEC",
        applicable_forms=("10-K", "10-Q", "8-K"),
        candidate_tiers=("tier1", "tier2"),
        veto_signals=("conflict", "invalid"),
    )
    assert profile.profile_id == "default"
    assert profile.applicable_forms == ("10-K", "10-Q", "8-K")
    assert profile.veto_signals == ("conflict", "invalid")
