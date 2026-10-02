"""Compositional SEC cover capability groups and form-family profiles.

Capability groups are the smallest reusable units of cover vocabulary. Profiles
select groups rather than re-declaring field lists, so annual-only anchors
(``documents_incorporated_reference``, public float, annual share-count
wording, auditor disclosures) can never leak into quarterly, current-report,
or no-cover processing.

A profile is the only object the normalization stages consult. It carries the
boundary capabilities the detector may use, the typed evidence packs the
detector matches against, and the vocabulary each later stage is allowed to
rewrite. A family whose profile has no boundary policy performs no cover
processing at all.

The label groups below are the vocabulary enabled for cover-candidate table
detection. Annual and quarterly covers share the core identity and contact
labels; annual adds no label of its own because every annual-only anchor is a
phrase-healing rule rather than a caption.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace as _dataclass_replace
from typing import TYPE_CHECKING

from edgar_sec.domain.forms.common.aliases import resolve_alias
from edgar_sec.domain.forms.common.models import (
    BodyEvidencePack,
    CoverEvidencePack,
)
from edgar_sec.domain.forms.common.rules import COMMON_PHRASE_RULES
from edgar_sec.domain.forms.common.vocabulary import (
    COVER_EVIDENCE_TERMS,
    COVER_LABELS_FLAT,
    COVER_START_IDENTITY_TERMS,
)
from edgar_sec.domain.forms.families.annual.checkmarks import ANNUAL_CHECKBOX_SCHEMA
from edgar_sec.domain.forms.families.annual.evidence import (
    ANNUAL_ADDITIONAL_PHRASE_RULES,
    AnnualReportEvidence,
)
from edgar_sec.domain.forms.families.annual.taxonomy import (
    FORM_10K_DERIVED,
    FORM_20F_DERIVED,
)
from edgar_sec.domain.forms.families.current_report.evidence import (
    CurrentReportEvidence,
)
from edgar_sec.domain.forms.families.current_report.taxonomy import FORM_8K_ITEMS
from edgar_sec.domain.forms.families.quarterly.checkmarks import (
    QUARTERLY_CHECKBOX_SCHEMA,
)
from edgar_sec.domain.forms.families.quarterly.evidence import (
    QuarterlyReportEvidence,
)
from edgar_sec.domain.forms.families.quarterly.taxonomy import FORM_10Q_DERIVED
from edgar_sec.engine.forms.cover.models import (
    BoundarySignal,
    CoverBoundaryPolicy,
)

if TYPE_CHECKING:
    from edgar_sec.domain.forms.common.schemas import CoverCheckboxSchema
    from edgar_sec.foundation.text.healing import PhraseSequenceRule


COMMON_COVER_LABELS: tuple[str, ...] = COVER_LABELS_FLAT

ANNUAL_COVER_LABELS: tuple[str, ...] = COMMON_COVER_LABELS
QUARTERLY_COVER_LABELS: tuple[str, ...] = COMMON_COVER_LABELS
NO_COVER_LABELS: tuple[str, ...] = ()

QUARTERLY_PHRASE_RULES: tuple[PhraseSequenceRule, ...] = tuple(COMMON_PHRASE_RULES)
NO_COVER_PHRASE_RULES: tuple[PhraseSequenceRule, ...] = ()


@dataclass(frozen=True, slots=True)
class CoverProfile:
    """Immutable, typed description of cover processing for one form family.

    Attributes:
        family: Canonical form family name used for registry lookup.
        boundary: Boundary evidence capabilities, or ``None`` for no cover.
        labels: Label terms used to mark cover-candidate tables.
        evidence_terms: Additional caption terms used for candidate detection.
        healing_rules: Phrase-healing rules enabled by this profile.
        cover_evidence: Typed evidence pack for cover-start/end detection.
        body_evidence: Typed evidence pack for body-anchor detection.
        derived_taxonomy: Item/part taxonomy derived vocabulary for TOC and
            body matching, or ``None`` when the family declares none.
        checkbox_schema: Form-scoped checkbox constraints, or ``None`` for
            forms without a cover checkbox schema.
        cover_table_cleaners: Named cover-table cleaners this family enables.
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


def _make_profile(
    family: str,
    boundary: CoverBoundaryPolicy | None,
    labels: tuple[str, ...],
    healing_rules: tuple[PhraseSequenceRule, ...],
    cover_evidence: CoverEvidencePack | None = None,
    body_evidence: BodyEvidencePack | None = None,
    derived_taxonomy: dict | None = None,
    checkbox_schema: CoverCheckboxSchema | None = None,
    cover_table_cleaners: tuple[str, ...] = (),
) -> CoverProfile:
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
        checkbox_schema=checkbox_schema,
        cover_table_cleaners=cover_table_cleaners,
    )


def build_annual_profile(family: str) -> CoverProfile:
    """Build a cover profile for annual and foreign annual reports.

    Annual covers are the only family allowed to end on an
    incorporated-by-reference block, so only this profile enables that
    boundary signal and carries the annual healing rules.

    The ``AMENDMENT_TRANSITION`` signal is also enabled so that 10-K/A
    amendments whose cover pages are not followed by a full PART I → ITEM 1
    sequence (instead terminating into EXPLANATORY NOTE, REPORT OF INDEPENDENT
    AUDITORS, or SIGNATURES) can still receive a valid cover boundary.
    """
    annual = AnnualReportEvidence()
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
            # Expand to all canonical SEC Items so that 10-K/A amendments that
            # start at Item 8, 10-15 (auditor reports, Part III, exhibits) are
            # covered by the structural scanner, not just base-10K Item 1.
            structural_headings=(
                "PART I",
                "ITEM 1",
                "ITEM 1A",
                "ITEM 1B",
                "ITEM 1C",
                "ITEM 2",
                "ITEM 3",
                "ITEM 4",
                "ITEM 5",
                "ITEM 6",
                "ITEM 7",
                "ITEM 7A",
                "ITEM 8",
                "ITEM 9",
                "ITEM 9A",
                "ITEM 9B",
                "ITEM 9C",
                "ITEM 10",
                "ITEM 11",
                "ITEM 12",
                "ITEM 13",
                "ITEM 14",
                "ITEM 15",
            ),
            semantic_headings=(
                "management's discussion and analysis",
                "risk factors",
                "forward-looking statements",
                "forward looking statements",
                "forward looking information",
                "special note regarding forward-looking",
                "special note regarding forward looking",
                "cautionary statements",
                "cautionary note",
                "safe harbor",
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
        checkbox_schema=ANNUAL_CHECKBOX_SCHEMA,
        cover_table_cleaners=("report_period",),
    )


def build_quarterly_profile(family: str) -> CoverProfile:
    """Build a cover profile for quarterly reports.

    A quarterly cover carries no incorporated-by-reference block, so it enables
    the same signals as the annual profile minus that one and heals only the
    shared cover vocabulary.
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
                "forward-looking statements",
                "forward looking statements",
                "forward looking information",
                "cautionary statements",
                "cautionary note",
                "safe harbor",
            ),
            body_ngrams=quarterly.body_ngrams,
            body_verbs=quarterly.body_verbs,
            lexical=quarterly.body_lexical,
        ),
        checkbox_schema=QUARTERLY_CHECKBOX_SCHEMA,
        cover_table_cleaners=("report_period",),
    )


def build_current_report_profile(family: str) -> CoverProfile:
    """Build a cover profile for current reports (8-K, 6-K).

    A current report has no cover page, so it declares no boundary policy and
    no cover evidence; the item headings are its only structural evidence.
    """
    current = CurrentReportEvidence()
    structural_headings = tuple(d.item for d in FORM_8K_ITEMS)
    return _make_profile(
        family=family,
        boundary=None,
        labels=NO_COVER_LABELS,
        healing_rules=NO_COVER_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=(),
            shape_terms=(),
            labels=NO_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=structural_headings,
            semantic_headings=(
                "item",
                "forward-looking statements",
                "forward looking statements",
                "forward looking information",
                "cautionary statements",
                "cautionary note",
                "safe harbor",
                "signature",
                "signatures",
            ),
            body_ngrams=current.body_ngrams,
            body_verbs=current.body_verbs,
            body_terms=current.body_terms,
            lexical=current.body_lexical,
        ),
    )


def build_no_cover_profile(family: str) -> CoverProfile:
    """Build a no-cover profile for event-driven and other forms."""
    return _make_profile(
        family=family,
        boundary=None,
        labels=NO_COVER_LABELS,
        healing_rules=NO_COVER_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=(),
            shape_terms=(),
            labels=NO_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(),
    )


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
    no_cover_8k = build_current_report_profile("8-K")
    current = CurrentReportEvidence()
    no_cover_6k = _dataclass_replace(
        no_cover_8k,
        family="6-K",
        body_evidence=BodyEvidencePack(
            structural_headings=(),
            semantic_headings=(
                "signatures",
                "signature",
                "exhibit",
                "press release",
                "forward-looking statements",
                "forward looking statements",
                "cautionary note",
            ),
            body_ngrams=current.body_ngrams,
            body_verbs=current.body_verbs,
            body_terms=current.body_terms,
            lexical=current.body_lexical,
        ),
    )
    generic = build_no_cover_profile("GENERIC")
    return {
        "10-K": annual_common,
        "20-F": annual_foreign,
        "10-Q": quarterly,
        "8-K": no_cover_8k,
        "6-K": no_cover_6k,
        "GENERIC": generic,
    }


COVER_PROFILES: dict[str, CoverProfile] = _build_profiles()


def get_profile(family: str | None) -> CoverProfile:
    """Return the cover profile for a form family, falling back to generic.

    The family is resolved through the canonical alias table, so an amendment
    or submission suffix (``10-K405/A``) selects the same profile as its base
    form. An unknown or missing family yields the no-cover generic profile
    rather than an error, because an unrecognized form must never be given
    cover-processing capabilities by accident.
    """
    if not family:
        return COVER_PROFILES["GENERIC"]
    family = resolve_alias(family) or family
    return COVER_PROFILES.get(family.upper(), COVER_PROFILES["GENERIC"])


__all__ = [
    "ANNUAL_COVER_LABELS",
    "COMMON_COVER_LABELS",
    "COVER_PROFILES",
    "NO_COVER_LABELS",
    "NO_COVER_PHRASE_RULES",
    "QUARTERLY_COVER_LABELS",
    "QUARTERLY_PHRASE_RULES",
    "CoverProfile",
    "build_annual_profile",
    "build_current_report_profile",
    "build_no_cover_profile",
    "build_quarterly_profile",
    "get_profile",
]
