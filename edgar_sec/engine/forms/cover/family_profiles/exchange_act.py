"""Cover profiles for the Exchange Act notice and Section 12
registration families (15, 12B-25, 25, 8-A, 8-B), composed from the
shared kit in ``profiles``."""

from __future__ import annotations

from edgar_sec.domain.forms.common.forward_looking import FORWARD_LOOKING_PHRASES
from edgar_sec.domain.forms.common.models import (
    BodyEvidencePack,
    CoverEvidencePack,
)
from edgar_sec.domain.forms.common.vocabulary import COVER_START_IDENTITY_TERMS
from edgar_sec.domain.forms.families.form_12b25.taxonomy import FORM_12B25_ITEMS
from edgar_sec.domain.forms.families.form_12reg.taxonomy import FORM_8A_ITEMS
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


_FORM_12REG_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "notification of removal from listing and/or registration",
    "exact name of issuer as specified in its charter",
    "description of class of securities",
    "for registration of certain classes of securities",
    "title of each class",
    "name of each exchange on which",
    "securities to be registered pursuant to section 12(b)",
    "securities to be registered pursuant to section 12(g)",
    "information required in registration statement",
)


def build_form_12reg_profile(family: str) -> CoverProfile:
    """Cover profile for the Section 12 cluster: the 25 notice face and
    the 8-A / 8-B registration covers with their class tables.
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
        labels=_FORM_12REG_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=_FORM_12REG_COVER_LABELS,
            labels=_FORM_12REG_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=tuple(d.item for d in FORM_8A_ITEMS),
            semantic_headings=(
                "description of securities to be registered",
                "description of registrant's securities to be registered",
                "description of registrant’s securities to be registered",
                "exhibits",
                "signature",
                "signatures",
                *FORWARD_LOOKING_PHRASES,
            ),
        ),
    )


__all__ = [
    "build_form_12b25_profile",
    "build_form_12reg_profile",
    "build_form_15_profile",
]
