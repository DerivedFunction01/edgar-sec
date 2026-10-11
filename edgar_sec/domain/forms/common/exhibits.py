"""S10 document role assessment data contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

EVALUATOR_VERSION = "v1"
TAXONOMY_VERSION = "v1"


@dataclass(frozen=True, slots=True)
class ExhibitIdentity:
    """Authority-qualified exhibit identifier."""

    authority_id: str
    code: str


@dataclass(frozen=True, slots=True)
class EvidenceSpan:
    """Half-open character span in normalized text passed to the evaluator."""

    signal_id: str
    start_char: int
    end_char: int


@dataclass(frozen=True, slots=True)
class DocumentRoleAssessment:
    """S10 role-assessment result for one document body."""

    expected_role: Literal["primary", "exhibit"]
    expected_type: str
    filing_form: str
    expected_identity: str | ExhibitIdentity | None
    observed_kind: Literal["primary_report", "exhibit", "unknown"]
    observed_identity: str | ExhibitIdentity | None
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
            "form_mismatch", "suspected_misfiled_exhibit", "suspected_misfiled_primary"
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


__all__ = ["DocumentRoleAssessment", "ExhibitIdentity", "EvidenceSpan"]
