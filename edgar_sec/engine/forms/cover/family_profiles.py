"""Cover profiles for the notice and prospectus families (15, 12B-25,
14A, 11-K, 424B), composed from the shared kit in ``profiles``.
"""

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
from edgar_sec.domain.forms.families.form_12b25.taxonomy import FORM_12B25_ITEMS
from edgar_sec.domain.forms.families.form_14a.evidence import Form14AEvidence
from edgar_sec.domain.forms.families.form_14a.taxonomy import FORM_14A_ITEMS
from edgar_sec.domain.forms.families.form_424b.taxonomy import FORM_424B_ITEMS
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


_FORM_15_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "certification and notice of termination of registration",
    "title of each class of securities covered by this form",
    "titles of all other classes of securities",
    "rule 12g-4",
    "rule 12h-3",
    "rule 15d-6",
    "approximate number of holders of record",
)


def build_form_15_profile(family: str = "15") -> CoverProfile:
    """Cover profile for Form 15 notices: a single-page cover carrying the
    rule-provision checkboxes; the body is footnotes plus the signature block.
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
        labels=_FORM_15_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=_FORM_15_COVER_LABELS,
            labels=_FORM_15_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            semantic_headings=(
                "signature",
                "signatures",
                *FORWARD_LOOKING_PHRASES,
            ),
        ),
    )


_FORM_12B25_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "notification of late filing",
    "sec file number",
    "cusip number",
    "for period ended",
    "transition report",
    "full name of registrant",
    "registrant information",
)


def build_form_12b25_profile(family: str = "12B-25") -> CoverProfile:
    """Cover profile for Form 12b-25 notifications: the filing selections and
    Part I registrant block form the cover; Parts II–IV are the body.
    """
    return _make_profile(
        family=family,
        boundary=CoverBoundaryPolicy(
            signals=(
                BoundarySignal.COVER_IDENTITY_AND_LAYOUT,
                BoundarySignal.PAGE_MARKERS,
                BoundarySignal.PART_FALLBACK,
                BoundarySignal.ITEM_FALLBACK,
                BoundarySignal.BODY_PROSE_FALLBACK,
            )
        ),
        labels=_FORM_12B25_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=_FORM_12B25_COVER_LABELS,
            labels=_FORM_12B25_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=tuple(d.item for d in FORM_12B25_ITEMS),
            semantic_headings=(
                "narrative",
                "other information",
                "signature",
                "signatures",
                *FORWARD_LOOKING_PHRASES,
            ),
        ),
    )


_FORM_14A_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "schedule 14a information",
    "schedule 14c information",
    "proxy statement pursuant to section 14(a)",
    "information statement pursuant to section 14(c)",
    "preliminary proxy statement",
    "definitive proxy statement",
    "name of registrant as specified in its charter",
    "name of person(s) filing proxy statement",
    "payment of filing fee",
)


def build_form_14a_profile(family: str = "14A") -> CoverProfile:
    """Cover profile for Schedule 14A/14C statements: the classification and
    fee boxes form the cover; the letter, contents, and Items 1–25 are the body.
    """
    proxy = Form14AEvidence()
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
        labels=_FORM_14A_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=_FORM_14A_COVER_LABELS,
            labels=_FORM_14A_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=tuple(d.item for d in FORM_14A_ITEMS),
            semantic_headings=(
                "notice of annual meeting",
                "notice of special meeting",
                "table of contents",
                "proxy statement",
                "signature",
                "signatures",
                *FORWARD_LOOKING_PHRASES,
            ),
            body_ngrams=proxy.body_ngrams,
            body_verbs=proxy.body_verbs,
            body_terms=proxy.body_terms,
            cover_terms=proxy.cover_terms,
            lexical=proxy.body_lexical,
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


__all__ = [
    "build_form_11k_profile",
    "build_form_12b25_profile",
    "build_form_14a_profile",
    "build_form_15_profile",
    "build_form_424b_profile",
]
