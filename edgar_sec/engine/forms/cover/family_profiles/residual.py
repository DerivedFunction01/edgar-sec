"""Cover profiles for the families whose report kind has no sibling
in the registry (SD specialized disclosure, DRS draft registration
submissions), composed from the shared kit in ``profiles``."""

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
from edgar_sec.domain.forms.families.form_sd.taxonomy import FORM_SD_ITEMS
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

_FORM_SD_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "specialized disclosure report",
    "check the appropriate box to indicate the rule pursuant to which this form is being filed",
    "exact name of registrant as specified in its charter",
    "name and telephone number, including area code, of the person to contact in connection with this report",
    "name and telephone number, including area code, of person to contact in connection with this report",
    "rule 13p-1 under the securities exchange act",
    "rule 13q-1 under the securities exchange act",
    "conflict minerals disclosure",
    "resource extraction issuer disclosure",
)


def build_form_sd_profile(family: str = "SD") -> CoverProfile:
    """Cover profile for Form SD: the thin face is the cover; the
    Sections 1–3 items and signatures are the body.
    """
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
        labels=_FORM_SD_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=_FORM_SD_COVER_LABELS,
            labels=_FORM_SD_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=tuple(d.item for d in FORM_SD_ITEMS),
            semantic_headings=(
                "conflict minerals disclosure and report",
                "resource extraction issuer disclosure and report",
                "resource extraction issuer disclosure report",
                "exhibits",
                "exhibit",
                "signature",
                "signatures",
                *FORWARD_LOOKING_PHRASES,
            ),
        ),
    )


_DRS_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "as confidentially submitted",
    "confidentially submitted",
    "draft registration statement",
    "confidential draft submission",
    "has not been publicly filed",
    "registration statement",
    "form s-1",
    "form s-3",
    "form f-1",
)


def build_form_drs_profile(family: str = "DRS") -> CoverProfile:
    """Cover profile for DRS submissions: the confidential banner heads
    the cover; the face and body inside are the base form's own.
    """
    registration = RegistrationEvidence()
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
        labels=_DRS_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=(
                *COMMON_COVER_LABELS,
                *COVER_EVIDENCE_TERMS,
                *_DRS_COVER_LABELS,
            ),
            labels=_DRS_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=("PART I", "PART II"),
            semantic_headings=(
                "prospectus summary",
                "risk factors",
                "use of proceeds",
                "dilution",
                "capitalization",
                "plan of distribution",
                "underwriting",
                "where you can find more information",
                "preliminary prospectus",
                "subject to completion",
                "index to consolidated financial statements",
                *FORWARD_LOOKING_PHRASES,
            ),
            body_ngrams=registration.body_ngrams,
            body_verbs=registration.body_verbs,
            body_terms=registration.body_terms,
            cover_terms=registration.cover_terms,
            lexical=registration.body_lexical,
        ),
    )


__all__ = [
    "build_form_drs_profile",
    "build_form_sd_profile",
]
