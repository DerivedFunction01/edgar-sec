"""Compositional SEC cover capability groups and form-family profiles: a profile
selects groups rather than re-declaring field lists, so annual-only anchors cannot
leak into quarterly or current-report processing.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace as _dataclass_replace
from typing import TYPE_CHECKING

from edgar_sec.domain.forms.common.aliases import resolve_alias
from edgar_sec.domain.forms.common.forward_looking import FORWARD_LOOKING_PHRASES
from edgar_sec.domain.forms.common.models import (
    BodyEvidencePack,
    CoverEvidencePack,
)
from edgar_sec.domain.forms.common.rules import COMMON_PHRASE_RULES
from edgar_sec.domain.forms.families.processing_profiles import get_family_entry
from edgar_sec.domain.forms.common.vocabulary import (
    COVER_EVIDENCE_TERMS,
    COVER_LABELS_FLAT,
    COVER_START_IDENTITY_TERMS,
)
from edgar_sec.domain.forms.families.annual.evidence import (
    ANNUAL_ADDITIONAL_PHRASE_RULES,
    AnnualReportEvidence,
)
from edgar_sec.domain.forms.families.annual.taxonomy import (
    FORM_10K_DERIVED,
    FORM_10K_ITEMS,
    FORM_20F_DERIVED,
)
from edgar_sec.domain.forms.families.current.evidence import (
    CURRENT_COVER_TERMS,
    CurrentReportEvidence,
)
from edgar_sec.domain.forms.families.current.taxonomy import FORM_8K_ITEMS
from edgar_sec.domain.forms.families.quarterly.evidence import (
    QuarterlyReportEvidence,
)
from edgar_sec.domain.forms.families.quarterly.taxonomy import FORM_10Q_DERIVED
from edgar_sec.domain.forms.families.registration.evidence import (
    REGISTRATION_SHAPE_TERMS,
    RegistrationEvidence,
)
from edgar_sec.domain.forms.families.registration.taxonomy import (
    FORM_S1_DERIVED,
    FORM_S1_ITEMS,
    FORM_S3_DERIVED,
    FORM_S4_DERIVED,
    FORM_S8_DERIVED,
)
from edgar_sec.engine.forms.cover.models import (
    BoundarySignal,
    CoverBoundaryPolicy,
)

if TYPE_CHECKING:
    from edgar_sec.domain.forms.common.processing import DocumentProcessingProfile
    from edgar_sec.domain.forms.common.schemas import CoverCheckboxSchema
    from edgar_sec.foundation.text.healing import PhraseSequenceRule


COMMON_COVER_LABELS: tuple[str, ...] = COVER_LABELS_FLAT

ANNUAL_COVER_LABELS: tuple[str, ...] = COMMON_COVER_LABELS
QUARTERLY_COVER_LABELS: tuple[str, ...] = COMMON_COVER_LABELS
GENERIC_COVER_LABELS: tuple[str, ...] = COMMON_COVER_LABELS
NO_COVER_LABELS: tuple[str, ...] = COMMON_COVER_LABELS

QUARTERLY_PHRASE_RULES: tuple[PhraseSequenceRule, ...] = tuple(COMMON_PHRASE_RULES)
GENERIC_PHRASE_RULES: tuple[PhraseSequenceRule, ...] = tuple(COMMON_PHRASE_RULES)
NO_COVER_PHRASE_RULES: tuple[PhraseSequenceRule, ...] = tuple(COMMON_PHRASE_RULES)


@dataclass(frozen=True, slots=True)
class CoverProfile:
    """Immutable cover processing for one form family, and the only object the
    normalization stages consult: boundary capabilities, packs, rewrite vocabulary.
    """

    family: str
    boundary: CoverBoundaryPolicy | None = None
    labels: tuple[str, ...] = ()
    evidence_terms: tuple[str, ...] = ()
    healing_rules: tuple[PhraseSequenceRule, ...] = ()
    cover_evidence: CoverEvidencePack | None = None
    body_evidence: BodyEvidencePack | None = None
    derived_taxonomy: dict | None = None
    checkbox_schema: CoverCheckboxSchema | None = None
    cover_table_cleaners: tuple[str, ...] = ()
    processing_profile: DocumentProcessingProfile | None = None

    @property
    def has_toc(self) -> bool:
        return self.processing_profile.has_toc if self.processing_profile else False

    @property
    def has_sections(self) -> bool:
        return (
            self.processing_profile.has_sections if self.processing_profile else False
        )

    @property
    def has_notes(self) -> bool:
        return self.processing_profile.has_notes if self.processing_profile else False

    @property
    def has_xbrl(self) -> bool:
        return self.processing_profile.has_xbrl if self.processing_profile else False

    @property
    def version(self) -> str:
        return self.processing_profile.version if self.processing_profile else "v1"


def _make_profile(
    family: str,
    boundary: CoverBoundaryPolicy | None,
    labels: tuple[str, ...],
    healing_rules: tuple[PhraseSequenceRule, ...],
    cover_evidence: CoverEvidencePack | None = None,
    body_evidence: BodyEvidencePack | None = None,
    derived_taxonomy: dict | None = None,
    cover_table_cleaners: tuple[str, ...] = (),
) -> CoverProfile:
    family_entry = get_family_entry(family)
    prof = family_entry.profile if family_entry is not None else None
    return CoverProfile(
        family=family,
        boundary=boundary,
        labels=labels,
        evidence_terms=(
            cover_evidence.shape_terms if cover_evidence is not None else ()
        ),
        healing_rules=healing_rules,
        cover_evidence=cover_evidence,
        body_evidence=body_evidence,
        derived_taxonomy=derived_taxonomy,
        checkbox_schema=(
            family_entry.cover_checkbox_schema if family_entry is not None else None
        ),
        cover_table_cleaners=cover_table_cleaners,
        processing_profile=prof,
    )


def build_annual_profile(family: str) -> CoverProfile:
    """Cover profile for annual reports: the only family allowed to end on an
    incorporated-by-reference block, and the only one enabling AMENDMENT_TRANSITION.
    """
    annual = AnnualReportEvidence()
    family_entry = get_family_entry(family)
    items = (
        family_entry.taxonomy_items
        if family_entry is not None and family_entry.taxonomy_items
        else FORM_10K_ITEMS
    )
    headings = ("PART I", *(d.item for d in items))
    return _make_profile(
        family=family,
        boundary=CoverBoundaryPolicy(
            signals=(
                BoundarySignal.COVER_IDENTITY_AND_LAYOUT,
                BoundarySignal.PAGE_MARKERS,
                BoundarySignal.INCORPORATED_REFERENCE,
                BoundarySignal.TOC_TRANSITION,
                BoundarySignal.PART_FALLBACK,
                BoundarySignal.AMENDMENT_TRANSITION,
                BoundarySignal.ITEM_FALLBACK,
                BoundarySignal.BODY_PROSE_FALLBACK,
            )
        ),
        labels=ANNUAL_COVER_LABELS,
        healing_rules=tuple(COMMON_PHRASE_RULES)
        + tuple(ANNUAL_ADDITIONAL_PHRASE_RULES),
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
            structural_headings=headings,
            semantic_headings=(
                "management's discussion and analysis",
                "risk factors",
                *FORWARD_LOOKING_PHRASES,
                "glossary of",
                "definitions",
                # Amendment-specific semantic anchors
                "explanatory note",
                "explanatory statement",
                "report of independent registered public accounting firm",
                "report of independent auditors",
                "index to consolidated financial statements",
            ),
            body_ngrams=annual.body_ngrams,
            body_verbs=annual.body_verbs,
            body_terms=annual.body_terms,
            cover_terms=annual.cover_terms,
            lexical=annual.body_lexical,
        ),
        cover_table_cleaners=("report_period",),
    )


def build_quarterly_profile(family: str) -> CoverProfile:
    """Cover profile for quarterly reports: no incorporated-by-reference or
    public-float block, so only shared identity and share-count vocabulary.
    """
    quarterly = QuarterlyReportEvidence()
    return _make_profile(
        family=family,
        boundary=CoverBoundaryPolicy(
            signals=(
                BoundarySignal.COVER_IDENTITY_AND_LAYOUT,
                BoundarySignal.PAGE_MARKERS,
                BoundarySignal.TOC_TRANSITION,
                BoundarySignal.PART_FALLBACK,
                BoundarySignal.ITEM_FALLBACK,
                BoundarySignal.BODY_PROSE_FALLBACK,
            )
        ),
        labels=QUARTERLY_COVER_LABELS,
        healing_rules=QUARTERLY_PHRASE_RULES,
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
                *FORWARD_LOOKING_PHRASES,
                "notes to condensed consolidated financial statements",
                "condensed consolidated financial statements",
            ),
            body_ngrams=quarterly.body_ngrams,
            body_verbs=quarterly.body_verbs,
            body_terms=quarterly.body_terms,
            cover_terms=quarterly.cover_terms,
            lexical=quarterly.body_lexical,
        ),
        cover_table_cleaners=("report_period",),
    )


def build_current_profile(family: str) -> CoverProfile:
    """Cover profile for current reports (8-K, 6-K): a statutory cover page
    transitioning directly into item events or signatures.
    """
    current = CurrentReportEvidence()
    structural_headings = tuple(d.item for d in FORM_8K_ITEMS)
    return _make_profile(
        family=family,
        boundary=CoverBoundaryPolicy(
            signals=(
                BoundarySignal.COVER_IDENTITY_AND_LAYOUT,
                BoundarySignal.PAGE_MARKERS,
                BoundarySignal.ITEM_FALLBACK,
                BoundarySignal.BODY_PROSE_FALLBACK,
            )
        ),
        labels=GENERIC_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=(*COMMON_COVER_LABELS, *CURRENT_COVER_TERMS),
            labels=COMMON_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=structural_headings,
            semantic_headings=(
                "item",
                *current.body_ngrams,
                *FORWARD_LOOKING_PHRASES,
                "signature",
                "signatures",
            ),
            body_ngrams=current.body_ngrams,
            body_verbs=current.body_verbs,
            body_terms=current.body_terms,
            cover_terms=current.cover_terms,
            lexical=current.body_lexical,
        ),
    )


def build_generic_cover_profile(family: str) -> CoverProfile:
    """Build a generic baseline cover profile for unspecialized or event-driven forms."""
    return _make_profile(
        family=family,
        boundary=CoverBoundaryPolicy(
            signals=(
                BoundarySignal.COVER_IDENTITY_AND_LAYOUT,
                BoundarySignal.PAGE_MARKERS,
                BoundarySignal.BODY_PROSE_FALLBACK,
            )
        ),
        labels=GENERIC_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=COMMON_COVER_LABELS,
            labels=COMMON_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            semantic_headings=FORWARD_LOOKING_PHRASES,
        ),
    )


_REGISTRATION_DERIVED = {
    "S-1": FORM_S1_DERIVED,
    "S-3": FORM_S3_DERIVED,
    "S-4": FORM_S4_DERIVED,
    "S-8": FORM_S8_DERIVED,
}


def build_registration_profile(family: str) -> CoverProfile:
    """Cover profile for registration statements (Form S-1, S-3, S-4, S-8)."""
    registration = RegistrationEvidence()
    family_entry = get_family_entry(family)
    items = (
        family_entry.taxonomy_items
        if family_entry is not None and family_entry.taxonomy_items
        else FORM_S1_ITEMS
    )
    headings = ("PART I", "PART II", *(d.item for d in items))
    derived = _REGISTRATION_DERIVED.get(family, FORM_S1_DERIVED)
    return _make_profile(
        family=family,
        boundary=CoverBoundaryPolicy(
            signals=(
                BoundarySignal.COVER_IDENTITY_AND_LAYOUT,
                BoundarySignal.PAGE_MARKERS,
                BoundarySignal.TOC_TRANSITION,
                BoundarySignal.PART_FALLBACK,
                BoundarySignal.ITEM_FALLBACK,
                BoundarySignal.BODY_PROSE_FALLBACK,
            )
        ),
        labels=COMMON_COVER_LABELS,
        healing_rules=tuple(COMMON_PHRASE_RULES),
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=(
                *COMMON_COVER_LABELS,
                *COVER_EVIDENCE_TERMS,
                *REGISTRATION_SHAPE_TERMS,
            ),
            labels=COMMON_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=headings,
            semantic_headings=(
                "prospectus summary",
                "risk factors",
                "use of proceeds",
                "dilution",
                "capitalization",
                "plan of distribution",
                "underwriting",
                *FORWARD_LOOKING_PHRASES,
                "preliminary prospectus",
                "subject to completion",
                "index to consolidated financial statements",
            ),
            body_ngrams=registration.body_ngrams,
            body_verbs=registration.body_verbs,
            body_terms=registration.body_terms,
            cover_terms=registration.cover_terms,
            lexical=registration.body_lexical,
        ),
        derived_taxonomy=derived,
    )


def build_no_cover_profile(family: str) -> CoverProfile:
    """Build a generic baseline cover profile (alias for build_generic_cover_profile)."""
    return build_generic_cover_profile(family)


def _build_profiles() -> dict[str, CoverProfile]:
    annual_common = _dataclass_replace(
        build_annual_profile("10-K"), derived_taxonomy=FORM_10K_DERIVED
    )
    annual_foreign = _dataclass_replace(
        annual_common, family="20-F", derived_taxonomy=FORM_20F_DERIVED
    )
    quarterly = _dataclass_replace(
        build_quarterly_profile("10-Q"), derived_taxonomy=FORM_10Q_DERIVED
    )
    registration_s1 = build_registration_profile("S-1")
    registration_s3 = build_registration_profile("S-3")
    registration_s4 = build_registration_profile("S-4")
    registration_s8 = build_registration_profile("S-8")
    generic_8k = build_current_profile("8-K")
    current = CurrentReportEvidence()
    generic_6k = _dataclass_replace(
        build_current_profile("6-K"),
        body_evidence=BodyEvidencePack(
            structural_headings=(),
            semantic_headings=(
                "signatures",
                "signature",
                "exhibit",
                "press release",
                *FORWARD_LOOKING_PHRASES,
            ),
            body_ngrams=current.body_ngrams,
            body_verbs=current.body_verbs,
            body_terms=current.body_terms,
            lexical=current.body_lexical,
        ),
    )
    generic = build_generic_cover_profile("GENERIC")
    return {
        "10-K": annual_common,
        "20-F": annual_foreign,
        "10-Q": quarterly,
        "S-1": registration_s1,
        "S-3": registration_s3,
        "S-4": registration_s4,
        "S-8": registration_s8,
        "8-K": generic_8k,
        "6-K": generic_6k,
        "GENERIC": generic,
    }


COVER_PROFILES: dict[str, CoverProfile] = _build_profiles()

#: Family key of the profile every unmodelled form resolves to. A profile's
#: boundary policy is never ``None``, so no-cover is identified by this key.
GENERIC_PROFILE_FAMILY = "GENERIC"


def get_profile(family: str | None) -> CoverProfile:
    """The cover profile for a form family, falling back to generic. Resolved through
    the alias table, and an unknown family never gains cover capabilities.
    """
    if not family:
        return COVER_PROFILES["GENERIC"]
    family = resolve_alias(family) or family
    return COVER_PROFILES.get(family.upper(), COVER_PROFILES["GENERIC"])


__all__ = [
    "ANNUAL_COVER_LABELS",
    "COMMON_COVER_LABELS",
    "COVER_PROFILES",
    "GENERIC_COVER_LABELS",
    "GENERIC_PROFILE_FAMILY",
    "GENERIC_PHRASE_RULES",
    "NO_COVER_LABELS",
    "NO_COVER_PHRASE_RULES",
    "QUARTERLY_COVER_LABELS",
    "QUARTERLY_PHRASE_RULES",
    "CoverProfile",
    "build_annual_profile",
    "build_current_profile",
    "build_generic_cover_profile",
    "build_no_cover_profile",
    "build_quarterly_profile",
    "build_registration_profile",
    "get_profile",
]
