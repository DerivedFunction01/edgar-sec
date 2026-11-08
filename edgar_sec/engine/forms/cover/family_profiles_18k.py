"""Cover profile for Form 18-K, composed from the shared kit in ``profiles``."""

from __future__ import annotations

from edgar_sec.domain.forms.common.forward_looking import FORWARD_LOOKING_PHRASES
from edgar_sec.domain.forms.common.models import (
    BodyEvidencePack,
    CoverEvidencePack,
)
from edgar_sec.domain.forms.common.vocabulary import COVER_START_IDENTITY_TERMS
from edgar_sec.domain.forms.families.form_18k.taxonomy import FORM_18K_ITEMS
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


__all__ = ["build_form_18k_profile"]
