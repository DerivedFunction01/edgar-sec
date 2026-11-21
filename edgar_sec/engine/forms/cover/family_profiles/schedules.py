"""Cover profiles for the schedule-statement families (SC TO tender
offers, Schedule 14A proxy statements), composed from the shared
kit in ``profiles``."""

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
from edgar_sec.domain.forms.families.form_14a.evidence import Form14AEvidence
from edgar_sec.domain.forms.families.form_14a.taxonomy import FORM_14A_ITEMS
from edgar_sec.domain.forms.families.form_tender.taxonomy import (
    SCHEDULE_13E3_ITEMS,
    SCHEDULE_13E3_PRIOR_ITEMS,
    SCHEDULE_13E4_ITEMS,
    SCHEDULE_14D1F_ITEMS,
    SCHEDULE_14D1_ITEMS,
    SCHEDULE_14D9_ITEMS,
    SCHEDULE_TO_ITEMS,
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

_TENDER_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "schedule to",
    "tender offer statement",
    "name of subject company",
    "names of filing persons",
    "name of filing person",
    "name of person filing statement",
    "title of class of securities",
    "cusip number of class of securities",
    "person authorized to receive notices and communications",
    "calculation of filing fee",
    "schedule 14d-9",
    "solicitation/recommendation statement",
    "schedule 13e-3",
    "rule 13e-3 transaction statement",
    "name of the issuer",
    "name of issuer",
    "names of persons filing statement",
    "schedule 13e-4",
    "issuer tender offer statement",
    "schedule 14d-1f",
    "check the appropriate boxes below to designate any transactions",
)

_TENDER_ITEM_SETS = (
    SCHEDULE_TO_ITEMS,
    SCHEDULE_14D9_ITEMS,
    SCHEDULE_13E3_ITEMS,
    SCHEDULE_13E3_PRIOR_ITEMS,
    SCHEDULE_13E4_ITEMS,
    SCHEDULE_14D1_ITEMS,
    SCHEDULE_14D1F_ITEMS,
)


def build_form_tender_profile(family: str = "SC TO") -> CoverProfile:
    """Cover profile for tender offer statements: the schedule facing
    sheet (subject company, filing persons, class, CUSIP, designation
    boxes) forms the cover; the body is the item sequence of its kind.
    """
    identifiers = tuple(
        dict.fromkeys(d.item for items in _TENDER_ITEM_SETS for d in items)
    )
    titles = tuple(
        dict.fromkeys(d.names[0] for items in _TENDER_ITEM_SETS for d in items)
    )
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
        labels=_TENDER_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=(
                *COMMON_COVER_LABELS,
                *COVER_EVIDENCE_TERMS,
                *_TENDER_COVER_LABELS,
            ),
            labels=_TENDER_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=identifiers,
            semantic_headings=(
                *titles,
                "signature",
                "signatures",
                *FORWARD_LOOKING_PHRASES,
            ),
        ),
        unwrap_false_tables=False,
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


__all__ = [
    "build_form_14a_profile",
    "build_form_tender_profile",
]
