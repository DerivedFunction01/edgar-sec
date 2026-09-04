"""Compositional SEC cover capability groups and form-family profiles.

Capability groups are the smallest reusable units of cover vocabulary. Profiles
select groups rather than re-declaring field lists, so annual-only anchors
(``documents_incorporated_reference``, public float, annual share-count
wording, auditor disclosures) can never leak into quarterly, current-report,
or no-cover processing.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace as _dataclass_replace
from typing import TYPE_CHECKING

from defs.sec_forms.cover.boundary import BoundarySignal, CoverBoundaryPolicy
from defs.sec_forms.forms.annual import ANNUAL_ADDITIONAL_PHRASE_RULES
from defs.sec_forms.forms.common import BodyEvidencePack, CoverEvidencePack
from defs.sec_forms.forms.profiles import (
    build_annual_profile,
    build_no_cover_profile,
    build_quarterly_profile,
)
from defs.sec_forms.sequences import COMMON_PHRASE_RULES, SEC_COVER_PHRASE_RULES
from defs.sec_forms.vocabulary import COVER_LABELS_FLAT
from defs.text import PhraseSequenceRule

if TYPE_CHECKING:
    from defs.tables.scope import TableScope


# --- Label groups --------------------------------------------------------------

# Labels enabled for cover-candidate table detection. Annual and quarterly
# covers share the core identity/contact labels; annual adds nothing extra
# here because the annual-only anchors are phrase-healing rules, not labels.
COMMON_COVER_LABELS: tuple[str, ...] = COVER_LABELS_FLAT

ANNUAL_COVER_LABELS: tuple[str, ...] = COMMON_COVER_LABELS
QUARTERLY_COVER_LABELS: tuple[str, ...] = COMMON_COVER_LABELS
NO_COVER_LABELS: tuple[str, ...] = ()

QUARTERLY_PHRASE_RULES: tuple[PhraseSequenceRule, ...] = tuple(COMMON_PHRASE_RULES)
NO_COVER_PHRASE_RULES: tuple[PhraseSequenceRule, ...] = ()


@dataclass(frozen=True)
class CoverProfile:
    """Immutable, typed description of cover processing for one form family.

    Attributes:
        family: Canonical form family name used for registry lookup.
        boundary: Boundary evidence capabilities, or ``None`` for no cover.
        table_scope: Table-scope capability used when applying templates to
            candidate tables.
        labels: Label terms used to mark cover-candidate tables.
        evidence_terms: Additional caption terms used for candidate detection.
        healing_rules: Phrase-healing rules enabled by this profile.
        cover_evidence: Typed evidence pack for cover-start/end detection.
        body_evidence: Typed evidence pack for body-anchor detection.
    """

    family: str
    boundary: CoverBoundaryPolicy | None
    table_scope: TableScope
    labels: tuple[str, ...]
    evidence_terms: tuple[str, ...]
    healing_rules: tuple[PhraseSequenceRule, ...]
    cover_evidence: CoverEvidencePack | None = None
    body_evidence: BodyEvidencePack | None = None
    derived_taxonomy: dict | None = None


def _make_profile(
    family: str,
    boundary: CoverBoundaryPolicy | None,
    table_scope: TableScope,
    labels: tuple[str, ...],
    healing_rules: tuple[PhraseSequenceRule, ...],
    cover_evidence: CoverEvidencePack | None = None,
    body_evidence: BodyEvidencePack | None = None,
    derived_taxonomy: dict | None = None,
) -> CoverProfile:
    return CoverProfile(
        family=family,
        boundary=boundary,
        table_scope=table_scope,
        labels=labels,
        evidence_terms=(
            cover_evidence.shape_terms if cover_evidence is not None else ()
        ),
        healing_rules=healing_rules,
        cover_evidence=cover_evidence,
        body_evidence=body_evidence,
        derived_taxonomy=derived_taxonomy,
    )


def _build_profiles() -> dict[str, CoverProfile]:
    from defs.sec_forms.forms.annual.taxonomy import (
        FORM_10K_DERIVED,
        FORM_20F_DERIVED,
    )
    from defs.sec_forms.forms.quarterly.taxonomy import FORM_10Q_DERIVED
    from defs.tables.templates import TableScope

    annual_evidence = build_annual_profile("10-K")
    quarterly_evidence = build_quarterly_profile("10-Q")
    no_cover_evidence = build_no_cover_profile("8-K")

    annual_common = _make_profile(
        family="10-K",
        boundary=CoverBoundaryPolicy(
            signals=(
                BoundarySignal.COVER_IDENTITY_AND_LAYOUT,
                BoundarySignal.PAGE_MARKERS,
                BoundarySignal.INCORPORATED_REFERENCE,
                BoundarySignal.TOC_TRANSITION,
                BoundarySignal.PART_FALLBACK,
                BoundarySignal.ITEM_FALLBACK,
            )
        ),
        table_scope=TableScope.COVER,
        labels=ANNUAL_COVER_LABELS,
        healing_rules=tuple(COMMON_PHRASE_RULES)
        + tuple(ANNUAL_ADDITIONAL_PHRASE_RULES),
        cover_evidence=annual_evidence.cover_evidence,
        body_evidence=annual_evidence.body_evidence,
        derived_taxonomy=FORM_10K_DERIVED,
    )
    annual_foreign = _dataclass_replace(
        annual_common, family="20-F", derived_taxonomy=FORM_20F_DERIVED
    )
    quarterly = _make_profile(
        family="10-Q",
        boundary=CoverBoundaryPolicy(
            signals=(
                BoundarySignal.COVER_IDENTITY_AND_LAYOUT,
                BoundarySignal.PAGE_MARKERS,
                BoundarySignal.TOC_TRANSITION,
                BoundarySignal.PART_FALLBACK,
                BoundarySignal.ITEM_FALLBACK,
            )
        ),
        table_scope=TableScope.COVER,
        labels=QUARTERLY_COVER_LABELS,
        healing_rules=QUARTERLY_PHRASE_RULES,
        cover_evidence=quarterly_evidence.cover_evidence,
        body_evidence=quarterly_evidence.body_evidence,
        derived_taxonomy=FORM_10Q_DERIVED,
    )
    no_cover_8k = _make_profile(
        family="8-K",
        boundary=None,
        table_scope=TableScope.BODY,
        labels=NO_COVER_LABELS,
        healing_rules=NO_COVER_PHRASE_RULES,
        cover_evidence=no_cover_evidence.cover_evidence,
        body_evidence=no_cover_evidence.body_evidence,
        derived_taxonomy=None,
    )
    no_cover_6k = _dataclass_replace(no_cover_8k, family="6-K")
    generic = _make_profile(
        family="GENERIC",
        boundary=None,
        table_scope=TableScope.BODY,
        labels=NO_COVER_LABELS,
        healing_rules=NO_COVER_PHRASE_RULES,
        cover_evidence=no_cover_evidence.cover_evidence,
        body_evidence=no_cover_evidence.body_evidence,
        derived_taxonomy=None,
    )
    return {
        "10-K": annual_common,
        "20-F": annual_foreign,
        "10-Q": quarterly,
        "8-K": no_cover_8k,
        "6-K": no_cover_6k,
        "GENERIC": generic,
    }


COVER_PROFILES: dict[str, CoverProfile] = _build_profiles()


def get_profile(family: str | None) -> CoverProfile:
    """Return the cover profile for a form family, falling back to generic."""
    if not family:
        return COVER_PROFILES["GENERIC"]
    return COVER_PROFILES.get(family.upper(), COVER_PROFILES["GENERIC"])


# The aggregate :data:`SEC_COVER_PHRASE_RULES` is re-exported from
# :mod:`defs.sec_forms.sequences` for callers that explicitly want the full
# annual rule set. The preprocessor consumes profile-selected tuples instead.


__all__ = [
    "ANNUAL_ADDITIONAL_PHRASE_RULES",
    "ANNUAL_COVER_LABELS",
    "COMMON_COVER_LABELS",
    "COMMON_PHRASE_RULES",
    "COVER_PROFILES",
    "NO_COVER_LABELS",
    "NO_COVER_PHRASE_RULES",
    "QUARTERLY_COVER_LABELS",
    "QUARTERLY_PHRASE_RULES",
    "SEC_COVER_PHRASE_RULES",
    "CoverProfile",
    "get_profile",
]
