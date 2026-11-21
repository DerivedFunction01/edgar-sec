"""Cover profiles for the annual-report families (18-K, 11-K, 40-F),
composed from the shared kit in ``profiles``."""

from __future__ import annotations

from edgar_sec.domain.forms.common.forward_looking import FORWARD_LOOKING_PHRASES
from edgar_sec.domain.forms.common.models import (
    BodyEvidencePack,
    CoverEvidencePack,
)
from edgar_sec.domain.forms.common.vocabulary import (
    COVER_EVIDENCE_TERMS,
    COVER_START_IDENTITY_TERMS,
)
from edgar_sec.domain.forms.families.form_11k.evidence import Form11KEvidence
from edgar_sec.domain.forms.families.form_11k.taxonomy import FORM_11K_ITEMS
from edgar_sec.domain.forms.families.form_18k.taxonomy import FORM_18K_ITEMS
from edgar_sec.domain.forms.families.form_40f.taxonomy import (
    FORM_40F_FURNISHED_KINDS,
)
from edgar_sec.domain.forms.families.registration.evidence import (
    RegistrationEvidence,
)
from edgar_sec.engine.forms.cover.models import (
    BoundarySignal,
    CoverBoundaryPolicy,
)
from edgar_sec.engine.forms.cover.profiles import (
    COMMON_COVER_LABELS,
    GENERIC_PHRASE_RULES,
    CoverProfile,
    _make_profile,
)

_FORM_18K_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "for foreign governments and political subdivisions thereof",
    "date of end of last fiscal year",
    "securities registered",
    "name and address of person authorized to receive notices and communications from the securities and exchange commission",
    "names and addresses of persons authorized to receive notices and communications from the securities and exchange commission",
)


def build_form_18k_profile(family: str = "18-K") -> CoverProfile:
    """Cover profile for Form 18-K: the face sheet with its registered
    securities table is the cover; the annual report body follows it.
    """
    return _make_profile(
        family=family,
        boundary=CoverBoundaryPolicy(
            signals=(
                BoundarySignal.COVER_IDENTITY_AND_LAYOUT,
                BoundarySignal.PAGE_MARKERS,
                BoundarySignal.BODY_PROSE_FALLBACK,
            )
        ),
        labels=_FORM_18K_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=_FORM_18K_COVER_LABELS,
            labels=_FORM_18K_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=tuple(d.item for d in FORM_18K_ITEMS),
            semantic_headings=(
                "explanatory note",
                "explanatory statement",
                *FORWARD_LOOKING_PHRASES,
            ),
        ),
    )


_FORM_11K_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "form 11-k",
    "annual reports of employee stock purchase, savings and similar plans",
    "commission file number",
    "full title of the plan",
    "name of issuer of the securities held pursuant to the plan",
    "for the fiscal year ended",
    "for the transition period from",
)


def build_form_11k_profile(family: str = "11-K") -> CoverProfile:
    """Cover profile for Form 11-K plan annual reports: the (Mark One) boxes,
    commission file number, and the plan/issuer captions form the cover; the
    financial statements and schedules are the body.
    """
    plan = Form11KEvidence()
    return _make_profile(
        family=family,
        boundary=CoverBoundaryPolicy(
            signals=(
                BoundarySignal.COVER_IDENTITY_AND_LAYOUT,
                BoundarySignal.PAGE_MARKERS,
                BoundarySignal.TOC_TRANSITION,
                BoundarySignal.ITEM_FALLBACK,
                BoundarySignal.BODY_PROSE_FALLBACK,
            )
        ),
        labels=_FORM_11K_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=_FORM_11K_COVER_LABELS,
            labels=_FORM_11K_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=tuple(d.item for d in FORM_11K_ITEMS),
            semantic_headings=(
                "financial statements and supplemental schedules",
                "report of independent registered public accounting firm",
                "signatures",
                "signature",
                *FORWARD_LOOKING_PHRASES,
            ),
            body_ngrams=plan.body_ngrams,
            body_verbs=plan.body_verbs,
            body_terms=plan.body_terms,
            cover_terms=plan.cover_terms,
            lexical=plan.body_lexical,
        ),
    )


_40F_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "form 40-f",
    "province or other jurisdiction",
    "registration statement under section 12",
    "annual report under section 13(a) or 15(d)",
    "for the fiscal year ended",
)


def build_form_40f_profile(family: str = "40-F") -> CoverProfile:
    """Cover profile for Form 40-F: the MJDS wrapper cover; the body is
    furnished Canadian documents, segmented by kind, not by item.
    """
    registration = RegistrationEvidence()
    furnished = tuple(
        phrase for phrases in FORM_40F_FURNISHED_KINDS.values() for phrase in phrases
    )
    return _make_profile(
        family=family,
        boundary=CoverBoundaryPolicy(
            signals=(
                BoundarySignal.COVER_IDENTITY_AND_LAYOUT,
                BoundarySignal.PAGE_MARKERS,
                BoundarySignal.TOC_TRANSITION,
                BoundarySignal.PART_FALLBACK,
                BoundarySignal.AMENDMENT_TRANSITION,
                BoundarySignal.BODY_PROSE_FALLBACK,
            )
        ),
        labels=_40F_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=(
                *COMMON_COVER_LABELS,
                *COVER_EVIDENCE_TERMS,
                *_40F_COVER_LABELS,
            ),
            labels=_40F_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=furnished,
            semantic_headings=(*furnished, *FORWARD_LOOKING_PHRASES),
            body_ngrams=registration.body_ngrams,
            body_verbs=registration.body_verbs,
            body_terms=registration.body_terms,
            cover_terms=registration.cover_terms,
            lexical=registration.body_lexical,
        ),
    )


__all__ = [
    "build_form_11k_profile",
    "build_form_18k_profile",
    "build_form_40f_profile",
]
