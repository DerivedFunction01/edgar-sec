"""Cover profiles for the prospectus and offering-communication
families (424B, FWP, 425, S-6), composed from the shared kit in
``profiles``."""

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
from edgar_sec.domain.forms.families.form_424b.taxonomy import FORM_424B_ITEMS
from edgar_sec.domain.forms.families.form_fwp.taxonomy import FORM_FWP_ITEMS
from edgar_sec.domain.forms.families.form_s6.taxonomy import FORM_S6_ITEMS
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

_FORM_424B_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "filed pursuant to rule 424",
    "registration no.",
    "registration statement no.",
    "registration number",
    "prospectus",
    "prospectus supplement",
    "preliminary prospectus",
    "pricing supplement",
    "subject to completion",
    "calculation of registration fee",
    "the date of this prospectus is",
)


def build_form_424b_profile(family: str = "424B") -> CoverProfile:
    """Cover profile for Rule 424 prospectuses: the 424(b) header block
    forms the cover; body vocabulary is the registration pack.
    """
    registration = RegistrationEvidence()
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
        labels=_FORM_424B_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=(
                *COMMON_COVER_LABELS,
                *COVER_EVIDENCE_TERMS,
                *_FORM_424B_COVER_LABELS,
            ),
            labels=_FORM_424B_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=tuple(d.item for d in FORM_424B_ITEMS),
            semantic_headings=(
                "prospectus summary",
                "risk factors",
                "use of proceeds",
                "plan of distribution",
                "underwriting",
                "table of contents",
                "calculation of registration fee",
                *FORWARD_LOOKING_PHRASES,
            ),
            body_ngrams=registration.body_ngrams,
            body_verbs=registration.body_verbs,
            body_terms=registration.body_terms,
            cover_terms=registration.cover_terms,
            lexical=registration.body_lexical,
        ),
    )


_FORM_FWP_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "free writing prospectus",
    "filed pursuant to rule 433",
    "registration statement nos.",
    "registration statement no.",
    "issuer",
    "guarantor",
)


def build_form_fwp_profile(family: str = "FWP") -> CoverProfile:
    """Cover profile for free writing prospectuses: the Rule 433 header
    block (issuer, rule reference, registration numbers) is the cover.
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
        labels=_FORM_FWP_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=(
                *COMMON_COVER_LABELS,
                *COVER_EVIDENCE_TERMS,
                *_FORM_FWP_COVER_LABELS,
            ),
            labels=_FORM_FWP_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=tuple(d.item for d in FORM_FWP_ITEMS),
            semantic_headings=(
                "summary terms",
                "key terms",
                "risk factors",
                *FORWARD_LOOKING_PHRASES,
            ),
        ),
    )


_FORM_425_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "filed by",
    "pursuant to rule 425",
    "rule 14a-12",
    "subject company",
    "commission file no.",
    "commission file number",
)


def build_form_425_profile(family: str = "425") -> CoverProfile:
    """Cover profile for Rule 425 communications: the filed-by / subject
    company header block is the cover; the body is the communication.
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
        labels=_FORM_425_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=(
                *COMMON_COVER_LABELS,
                *COVER_EVIDENCE_TERMS,
                *_FORM_425_COVER_LABELS,
            ),
            labels=_FORM_425_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=(),
            semantic_headings=(
                "press release",
                "forward-looking statements",
                *FORWARD_LOOKING_PHRASES,
            ),
        ),
    )


_FORM_S6_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "form s-6",
    "for registration under the securities act of 1933 of securities of unit investment trusts registered on form n-8b-2",
    "exact name of trust",
    "name of depositor",
    "title of securities being registered",
    "pursuant to rule 487",
    "subject to completion",
    "the date of this prospectus is",
)


def build_form_s6_profile(family: str = "S-6") -> CoverProfile:
    """Cover profile for Form S-6 UIT registrations: the facing sheet
    (trust, depositor, Rule 487 checkbox) is the cover; the priced
    prospectus body, including Rule 487 amendments, follows it.
    """
    registration = RegistrationEvidence()
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
        labels=_FORM_S6_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=(
                *COMMON_COVER_LABELS,
                *COVER_EVIDENCE_TERMS,
                *_FORM_S6_COVER_LABELS,
            ),
            labels=_FORM_S6_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=tuple(d.item for d in FORM_S6_ITEMS),
            semantic_headings=(
                "summary of essential information",
                "fee table",
                "risk factors",
                "public offering",
                "table of contents",
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
    "build_form_424b_profile",
    "build_form_425_profile",
    "build_form_fwp_profile",
    "build_form_s6_profile",
]
