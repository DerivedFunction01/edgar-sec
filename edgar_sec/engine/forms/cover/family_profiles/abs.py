"""Cover profile for the ABS text reports (10-D / ABS-15G), composed
from the shared kit in ``profiles``."""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import (
    BodyEvidencePack,
    CoverEvidencePack,
)
from edgar_sec.domain.forms.common.vocabulary import COVER_START_IDENTITY_TERMS
from edgar_sec.domain.forms.families.form_abs_reports.taxonomy import (
    ABS_REPORTS_ITEMS,
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

_ABS_REPORTS_COVER_LABELS: tuple[str, ...] = (
    *COMMON_COVER_LABELS,
    "asset-backed issuer distribution report pursuant to section 13 or 15(d)",
    "asset-backed securitizer report pursuant to section 15g",
    "form 10-d",
    "form abs-15g",
    "for the monthly distribution period from",
    "commission file number of issuing entity",
    "central index key number of issuing entity",
    "commission file number of depositor",
    "central index key number of depositor",
    "commission file number of depositor and sponsor",
    "central index key number of depositor and sponsor",
    "exact name of issuing entity as specified in its charter",
    "exact name of depositor as specified in its charter",
    "exact name of depositor and sponsor as specified in its charter",
    "exact name of sponsor as specified in its charter",
    "check the appropriate box to indicate the filing obligation",
    "rule 15ga-1 under the exchange act",
    "rule 15ga-2 under the exchange act",
    "commission file number of securitizer",
    "central index key number of securitizer",
    "date of report (date of earliest event reported)",
)


def build_form_abs_reports_profile(family: str) -> CoverProfile:
    """Cover profile for the ABS text reports: the 10-D distribution
    face and the ABS-15G securitizer face under one canonical family.
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
        labels=_ABS_REPORTS_COVER_LABELS,
        healing_rules=GENERIC_PHRASE_RULES,
        cover_evidence=CoverEvidencePack(
            identity_terms=COVER_START_IDENTITY_TERMS,
            shape_terms=_ABS_REPORTS_COVER_LABELS,
            labels=_ABS_REPORTS_COVER_LABELS,
        ),
        body_evidence=BodyEvidencePack(
            structural_headings=tuple(d.item for d in ABS_REPORTS_ITEMS),
            semantic_headings=(
                "distribution information",
                "representation and warranty information",
                "findings and conclusions of third-party due diligence reports",
                "legal proceedings",
                "exhibits",
                "exhibit index",
                "signature",
                "signatures",
            ),
        ),
    )


__all__ = [
    "build_form_abs_reports_profile",
]
