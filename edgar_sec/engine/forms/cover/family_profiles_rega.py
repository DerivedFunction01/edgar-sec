"""Cover profiles for the Regulation A text reports (1-SA, 1-U),
composed from the shared kit in ``profiles``.
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.forward_looking import FORWARD_LOOKING_PHRASES
from edgar_sec.domain.forms.common.models import (
    BodyEvidencePack,
    CoverEvidencePack,
)
from edgar_sec.domain.forms.common.vocabulary import COVER_START_IDENTITY_TERMS
from edgar_sec.domain.forms.families.form_rega.taxonomy import (
    FORM_1SA_ITEMS,
    FORM_1U_ITEMS,
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

_REGA_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "semiannual report pursuant to regulation a",
    "current report pursuant to regulation a",
    "for the fiscal semiannual period ended",
    "date of report (date of earliest event reported)",
    "exact name of issuer as specified in its charter",
    "exact name of registrant as specified in its charter",
    "full mailing address of principal executive offices",
    "issuer's telephone number, including area code",
    "issuer’s telephone number, including area code",
    "title of each class of securities issued pursuant to regulation a",
    "commission file no.",
)

_ITEMS_BY_FAMILY = {"1-SA": FORM_1SA_ITEMS, "1-U": FORM_1U_ITEMS}


def build_form_rega_profile(family: str) -> CoverProfile:
    """Cover profile for the Reg A report faces: the commission header,
    the period or event date line, and the class-of-securities caption.
    """
    items = _ITEMS_BY_FAMILY.get(family, ())
    return _make_profile(
        family=family,
        boundary=CoverBoundaryPolicy(
            signals=(
                BoundarySignal.COVER_IDENTITY_AND_LAYOUT,
                BoundarySignal.PAGE_MARKERS,
                BoundarySignal.ITEM_FALLBACK,
                BoundarySignal.BODY_PROSE_FALLBACK,
                BoundarySignal.TABLE_BODY_FALLBACK,
            )
        ),
        labels=_REGA_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=_REGA_COVER_LABELS,
            labels=_REGA_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=tuple(d.item for d in items),
            semantic_headings=(
                "management's discussion and analysis",
                "management’s discussion and analysis",
                "financial statements",
                "other information",
                "other events",
                "exhibits",
                "signature",
                "signatures",
                *FORWARD_LOOKING_PHRASES,
            ),
        ),
    )


__all__ = ["build_form_rega_profile"]
