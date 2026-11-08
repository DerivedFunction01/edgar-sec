"""Cover profiles for the foreign-issuer families (F-1/F-2, F-3, F-4),
the MJDS forms, F-6, SUPPL, and F-N, composed from the shared kit in
``profiles``."""

from __future__ import annotations

from edgar_sec.domain.forms.common.forward_looking import FORWARD_LOOKING_PHRASES
from edgar_sec.domain.forms.common.models import (
    BodyEvidencePack,
    CoverEvidencePack,
    ItemDefinition,
)
from edgar_sec.domain.forms.common.vocabulary import (
    COVER_EVIDENCE_TERMS,
    COVER_START_IDENTITY_TERMS,
)
from edgar_sec.domain.forms.families.form_f1.taxonomy import (
    FORM_F1_ITEMS,
    FORM_F2_ITEMS,
)
from edgar_sec.domain.forms.families.form_f3.taxonomy import FORM_F3_ITEMS
from edgar_sec.domain.forms.families.form_f4.taxonomy import FORM_F4_ITEMS
from edgar_sec.domain.forms.families.form_f6.taxonomy import FORM_F6_ITEMS
from edgar_sec.domain.forms.families.form_fn.taxonomy import (
    FORM_FN_LETTERED_ITEMS,
    FORM_FN_TITLES,
)
from edgar_sec.domain.forms.families.form_suppl.taxonomy import (
    FORM_SUPPL_BASE_PROSPECTUS_PHRASES,
    FORM_SUPPL_INSTRUCTION_REFERENCES,
    FORM_SUPPL_KINDS,
)
from edgar_sec.domain.forms.families.form_mjds.taxonomy import (
    FORM_F7_ITEMS,
    FORM_F8_ITEMS,
    FORM_F9_ITEMS,
    FORM_F10_ITEMS,
    FORM_F80_ITEMS,
    MJDS_PROSPECTUS_HEADINGS,
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

_REGISTRATION_F_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "calculation of registration fee",
    "registration no.",
    "registration statement no.",
    "registration number",
    "file no.",
    "files nos.",
    "registration statement under the securities act of 1933",
)


def _build_f_profile(
    family: str,
    items: tuple[ItemDefinition, ...],
    extra_labels: tuple[str, ...] = (),
) -> CoverProfile:
    registration = RegistrationEvidence()
    labels = (
        *_REGISTRATION_F_COVER_LABELS,
        f"form {family.lower()}",
        *extra_labels,
    )
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
        labels=labels,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=(
                *COMMON_COVER_LABELS,
                *COVER_EVIDENCE_TERMS,
                *labels,
            ),
            labels=labels,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=("PART I", "PART II", *(d.item for d in items)),
            semantic_headings=(
                *(d.names[0] for d in items),
                *FORWARD_LOOKING_PHRASES,
            ),
            body_ngrams=registration.body_ngrams,
            body_verbs=registration.body_verbs,
            body_terms=registration.body_terms,
            cover_terms=registration.cover_terms,
            lexical=registration.body_lexical,
        ),
    )


def build_form_f1_profile(family: str = "F-1") -> CoverProfile:
    """Cover profile for Forms F-1/F-2: the shared facing sheet forms the
    cover; body vocabulary is the family taxonomy plus the registration pack.
    """
    items = FORM_F2_ITEMS if family == "F-2" else FORM_F1_ITEMS
    return _build_f_profile(family, items)


def build_form_f3_profile(family: str = "F-3") -> CoverProfile:
    """Cover profile for Form F-3 shelf registration statements."""
    return _build_f_profile(
        family,
        FORM_F3_ITEMS,
        extra_labels=("automatic shelf registration statement",),
    )


def build_form_f4_profile(family: str = "F-4") -> CoverProfile:
    """Cover profile for Form F-4 business-combination registrations."""
    return _build_f_profile(family, FORM_F4_ITEMS)


_MJDS_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "registration no.",
    "registration statement no.",
    "registration statement under the securities act of 1933",
    "province or other jurisdiction",
    "multijurisdictional disclosure system",
    "it is proposed that this filing shall become effective",
    "check the appropriate box",
    "home jurisdiction",
)

_MJDS_ITEMS_BY_FAMILY: dict[str, tuple[ItemDefinition, ...]] = {
    "F-7": FORM_F7_ITEMS,
    "F-8": FORM_F8_ITEMS,
    "F-9": FORM_F9_ITEMS,
    "F-10": FORM_F10_ITEMS,
    "F-80": FORM_F80_ITEMS,
}

_MJDS_PROSPECTUS_FAMILIES = frozenset({"F-9", "F-10"})


def build_form_mjds_profile(family: str = "F-10") -> CoverProfile:
    """Cover profile for the MJDS forms: one wrapper cover; the body
    vocabulary is the form's tail taxonomy, plus the shelf-prospectus
    headings for F-9/F-10.
    """
    items = _MJDS_ITEMS_BY_FAMILY[family]
    registration = RegistrationEvidence()
    labels = (*_MJDS_COVER_LABELS, f"form {family.lower()}")
    prospectus = MJDS_PROSPECTUS_HEADINGS if family in _MJDS_PROSPECTUS_FAMILIES else ()
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
        labels=labels,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=(
                *COMMON_COVER_LABELS,
                *COVER_EVIDENCE_TERMS,
                *labels,
            ),
            labels=labels,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=(*(d.item for d in items), *prospectus),
            semantic_headings=(
                *(d.names[0] for d in items),
                *prospectus,
                *FORWARD_LOOKING_PHRASES,
            ),
            body_ngrams=registration.body_ngrams,
            body_verbs=registration.body_verbs,
            body_terms=registration.body_terms,
            cover_terms=registration.cover_terms,
            lexical=registration.body_lexical,
        ),
    )


_F6_COVER_LABELS: tuple[str, ...] = (
    *_REGISTRATION_F_COVER_LABELS,
    "form f-6",
    "depositary shares evidenced by american depositary receipts",
    "exact name of issuer of deposited securities",
    "exact name of depositary",
    "jurisdiction of incorporation or organization of issuer",
    "agent for service",
)

_F6_PROSPECTUS_HEADINGS: tuple[str, ...] = (
    "risk factors",
    "use of proceeds",
    "plan of distribution",
    "underwriting",
    "capitalization",
    "dilution",
)


def build_form_f6_profile(family: str = "F-6") -> CoverProfile:
    """Cover profile for Form F-6: dual-party depositary cover; the
    body is a short depositary prospectus plus the Part II tail.
    """
    registration = RegistrationEvidence()
    items = FORM_F6_ITEMS
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
        labels=_F6_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=(
                *COMMON_COVER_LABELS,
                *COVER_EVIDENCE_TERMS,
                *_F6_COVER_LABELS,
            ),
            labels=_F6_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=(
                *(d.item for d in items),
                *_F6_PROSPECTUS_HEADINGS,
            ),
            semantic_headings=(
                *(d.names[0] for d in items),
                *_F6_PROSPECTUS_HEADINGS,
                *FORWARD_LOOKING_PHRASES,
            ),
            body_ngrams=registration.body_ngrams,
            body_verbs=registration.body_verbs,
            body_terms=registration.body_terms,
            cover_terms=registration.cover_terms,
            lexical=registration.body_lexical,
        ),
    )


_SUPPL_COVER_LABELS: tuple[str, ...] = (
    "filed pursuant to general",
    *FORM_SUPPL_INSTRUCTION_REFERENCES,
    "file no.",
    *FORM_SUPPL_KINDS,
    *FORM_SUPPL_BASE_PROSPECTUS_PHRASES,
    "form f-9",
    "form f-10",
)


def build_form_suppl_profile(family: str = "SUPPL") -> CoverProfile:
    """Cover profile for SUPPL: the supplement caption block is the
    cover; the body is the supplement's own prospectus sections.
    """
    registration = RegistrationEvidence()
    return _make_profile(
        family=family,
        boundary=CoverBoundaryPolicy(
            signals=(
                BoundarySignal.COVER_IDENTITY_AND_LAYOUT,
                BoundarySignal.PAGE_MARKERS,
                BoundarySignal.TOC_TRANSITION,
                BoundarySignal.BODY_PROSE_FALLBACK,
            )
        ),
        labels=_SUPPL_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=(
                *COMMON_COVER_LABELS,
                *COVER_EVIDENCE_TERMS,
                *_SUPPL_COVER_LABELS,
            ),
            labels=_SUPPL_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=MJDS_PROSPECTUS_HEADINGS,
            semantic_headings=(
                *MJDS_PROSPECTUS_HEADINGS,
                *FORWARD_LOOKING_PHRASES,
            ),
            body_ngrams=registration.body_ngrams,
            body_verbs=registration.body_verbs,
            body_terms=registration.body_terms,
            cover_terms=registration.cover_terms,
            lexical=registration.body_lexical,
        ),
    )


_FN_COVER_LABELS: tuple[str, ...] = (
    *FORM_FN_TITLES,
    *(title for _, title in FORM_FN_LETTERED_ITEMS),
    "name of registrant",
    "file number",
    "filed by",
)


def build_form_fn_profile(family: str = "F-N") -> CoverProfile:
    """Cover profile for Form F-N: the printed appointment form is the
    whole document. Like Form 15, the body pack carries no registration
    vocabulary — the form's own prose is the cover.
    """
    lettered = tuple(title for _, title in FORM_FN_LETTERED_ITEMS)
    return _make_profile(
        family=family,
        boundary=CoverBoundaryPolicy(
            signals=(
                BoundarySignal.COVER_IDENTITY_AND_LAYOUT,
                BoundarySignal.PAGE_MARKERS,
                BoundarySignal.BODY_PROSE_FALLBACK,
            )
        ),
        labels=_FN_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=(
                *COMMON_COVER_LABELS,
                *COVER_EVIDENCE_TERMS,
                *_FN_COVER_LABELS,
            ),
            labels=_FN_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            semantic_headings=(
                *lettered,
                "signature",
                "signatures",
                *FORWARD_LOOKING_PHRASES,
            ),
        ),
    )


__all__ = [
    "build_form_f1_profile",
    "build_form_f3_profile",
    "build_form_f4_profile",
    "build_form_f6_profile",
    "build_form_fn_profile",
    "build_form_mjds_profile",
    "build_form_suppl_profile",
]
