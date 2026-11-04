"""Cover profile for Form SD, composed from the shared kit in ``profiles``."""

from __future__ import annotations

from edgar_sec.domain.forms.common.forward_looking import FORWARD_LOOKING_PHRASES
from edgar_sec.domain.forms.common.models import (
    BodyEvidencePack,
    CoverEvidencePack,
)
from edgar_sec.domain.forms.common.vocabulary import COVER_START_IDENTITY_TERMS
from edgar_sec.domain.forms.families.form_sd.taxonomy import FORM_SD_ITEMS
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
            BoundarySignal.TABLE_BODY_FALLBACK,
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


__all__ = ["build_form_sd_profile"]
