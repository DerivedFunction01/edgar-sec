"""S10 document role assessment data contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

EVALUATOR_VERSION = "v1"
TAXONOMY_VERSION = "v1"
PRIMARY_PROFILE_VERSION = "v1"
EX_PROFILE_VERSION = "v1"


@dataclass(frozen=True, slots=True)
class ExhibitIdentity:
    """Authority-qualified exhibit identifier."""

    authority_id: str
    code: str


@dataclass(frozen=True, slots=True)
class ScheduleIdentity:
    """Identifier for schedules (e.g. Schedule 14A, 13D)."""

    schedule: str


@dataclass(frozen=True, slots=True)
class EvidenceSpan:
    """Half-open character span in normalized text passed to the evaluator."""

    signal_id: str
    start_char: int
    end_char: int


@dataclass(frozen=True, slots=True)
class DocumentRoleAssessment:
    """S10 role-assessment result for one document body."""

    expected_role: Literal["primary", "exhibit", "schedule"]
    expected_type: str
    filing_form: str
    expected_identity: str | ExhibitIdentity | ScheduleIdentity | None
    observed_kind: Literal[
        "primary_report",
        "exhibit",
        "schedule",
        "structured_data",
        "paper_stub",
        "unknown",
    ]
    observed_identity: str | ExhibitIdentity | ScheduleIdentity | None
    disposition: Literal[
        "consistent", "possible_role_mismatch", "insufficient_evidence"
    ]
    evaluator_quality: Literal[
        "proposed",
        "source_supported",
        "fixture_reviewed",
        "shadow_reviewed",
        "holdout_evaluated",
    ]
    profile_id: str
    profile_version: str
    schema_version: int = 1
    evaluator_version: str = EVALUATOR_VERSION
    taxonomy_version: str = TAXONOMY_VERSION
    diagnostic_code: (
        Literal[
            "form_mismatch",
            "suspected_misfiled_exhibit",
            "suspected_misfiled_primary",
            "suspected_misfiled_schedule",
        ]
        | None
    ) = None
    diagnostic_detail: str | None = None
    supporting_evidence: tuple[EvidenceSpan, ...] = ()
    contradicting_evidence: tuple[EvidenceSpan, ...] = ()
    matched_evidence_tier: str | None = None
    confidence_band: Literal["insufficient", "low", "moderate", "high"] | None = None
    pack_id: str | None = None
    pack_version: str | None = None


@dataclass(frozen=True, slots=True)
class SourceRef:
    """Auditable citation linking a coverage entry to official sources or research."""

    source_path: str
    section_or_lines: str
    note: str = ""


CoverageStatus = Literal[
    "candidate", "partial", "unsupported", "reserved", "disabled", "historical"
]


@dataclass(frozen=True, slots=True)
class CoverageEntry:
    """Single source-of-truth ledger entry for an authority-qualified code."""

    authority_id: str
    code: str
    title: str
    coverage_status: CoverageStatus
    applicability: tuple[str, ...] = ()
    source_refs: tuple[SourceRef, ...] = ()
    pack_id: str | None = None
    evaluator_quality: Literal[
        "proposed",
        "source_supported",
        "fixture_reviewed",
        "shadow_reviewed",
        "holdout_evaluated",
    ] = "proposed"


@dataclass(frozen=True, slots=True)
class ExhibitAssessmentProfile:
    """Declarative profile governing applicability and candidate tiers."""

    profile_id: str
    version: str
    authority_id: str
    applicable_forms: tuple[str, ...]
    candidate_tiers: tuple[str, ...] = ()
    veto_signals: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PrimaryReportProfile:
    """Declarative profile for recognizing a primary statutory filing."""

    family: str
    version: str = PRIMARY_PROFILE_VERSION
    statutory_titles: tuple[str, ...] = ()
    designator_tokens: tuple[str, ...] = ()
    commission_header_required: bool = True


@dataclass(frozen=True, slots=True)
class ExhibitAuthorityProfile:
    """Declarative profile governing an exhibit authority namespace."""

    authority_id: str
    version: str = EX_PROFILE_VERSION
    applicable_forms: tuple[str, ...] = ()
    candidate_tiers: tuple[str, ...] = ()
    veto_signals: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExhibitPack:
    """Declarative evidence pack for an exhibit item or subtype."""

    pack_id: str
    version: str
    authority_id: str
    target_code: str
    title: str
    parent_code: str | None = None
    tier: Literal["tier1", "tier2", "tier3"] = "tier1"
    title_anchors: tuple[str, ...] = ()
    title_window_lines: int = 10
    primary_anchors: tuple[str, ...] = ()
    secondary_tokens: tuple[str, ...] = ()
    veto_signals: tuple[str, ...] = ()
    matched_evidence_tier: str = "direct_designator"
    min_confidence_band: Literal["insufficient", "low", "moderate", "high"] = "high"
    evaluator_quality: Literal[
        "proposed",
        "source_supported",
        "fixture_reviewed",
        "shadow_reviewed",
        "holdout_evaluated",
    ] = "source_supported"
    source_refs: tuple[SourceRef, ...] = ()


__all__ = [
    "EVALUATOR_VERSION",
    "TAXONOMY_VERSION",
    "ExhibitIdentity",
    "ScheduleIdentity",
    "EvidenceSpan",
    "DocumentRoleAssessment",
    "SourceRef",
    "CoverageStatus",
    "CoverageEntry",
    "ExhibitPack",
    "PrimaryReportProfile",
    "ExhibitAuthorityProfile",
]
