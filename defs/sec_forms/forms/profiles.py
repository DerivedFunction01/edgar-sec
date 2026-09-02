"""Cover-profile composition from form-family evidence packs."""

from __future__ import annotations

from dataclasses import dataclass

from defs.sec_forms.forms.annual import AnnualReportEvidence
from defs.sec_forms.forms.common import BodyEvidencePack, CoverEvidencePack
from defs.sec_forms.forms.quarterly import QuarterlyReportEvidence
from defs.sec_forms.vocabulary import (
    COVER_EVIDENCE_TERMS,
    COVER_LABELS_FLAT,
    COVER_START_IDENTITY_TERMS,
)

# Common cover labels used by every cover-bearing form family.
COMMON_COVER_LABELS: tuple[str, ...] = COVER_LABELS_FLAT

NO_COVER_LABELS: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CoverProfile:
    """Composed cover profile for a form family."""

    family: str
    boundary_enabled: bool
    cover_evidence: CoverEvidencePack
    body_evidence: BodyEvidencePack


def build_annual_profile(family: str) -> CoverProfile:
    """Build a cover profile for annual and foreign annual reports."""
    annual = AnnualReportEvidence()
    return CoverProfile(
        family=family,
        boundary_enabled=True,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=(
                *COMMON_COVER_LABELS,
                *COVER_EVIDENCE_TERMS,
                *annual.shape_terms,
            ),
            labels=COMMON_COVER_LABELS,
            cover_end_terms=annual.incorporated_reference_terms,
            healing_rules=annual.healing_rules,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=("PART I", "ITEM 1", "ITEM 1A"),
            semantic_headings=(
                "management's discussion and analysis",
                "risk factors",
                "forward-looking statements",
                "safe harbor",
            ),
            body_ngrams=annual.body_ngrams,
            body_verbs=annual.body_verbs,
            body_terms=annual.body_terms,
            cover_terms=annual.cover_terms,
            lexical=annual.body_lexical,
        ),
    )


def build_quarterly_profile(family: str) -> CoverProfile:
    """Build a cover profile for quarterly reports."""
    quarterly = QuarterlyReportEvidence()
    return CoverProfile(
        family=family,
        boundary_enabled=True,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=(*COMMON_COVER_LABELS, "section 12(b)"),
            labels=COMMON_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=("PART I", "ITEM 1"),
            semantic_headings=(
                "management's discussion and analysis",
                "quantitative and qualitative disclosures",
            ),
            body_ngrams=quarterly.body_ngrams,
            body_verbs=quarterly.body_verbs,
            lexical=quarterly.body_lexical,
        ),
    )


def build_no_cover_profile(family: str) -> CoverProfile:
    """Build a no-cover profile for event-driven and other forms."""
    return CoverProfile(
        family=family,
        boundary_enabled=False,
        cover_evidence=CoverEvidencePack(
            identity_terms=(),
            shape_terms=(),
            labels=NO_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(),
    )


__all__ = [
    "COMMON_COVER_LABELS",
    "NO_COVER_LABELS",
    "CoverProfile",
    "build_annual_profile",
    "build_no_cover_profile",
    "build_quarterly_profile",
]
