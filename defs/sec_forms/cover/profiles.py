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

from defs.sec_forms.cover.vocabulary import COVER_LABELS
from defs.sec_forms.sequences import (
    ANNUAL_ADDITIONAL_PHRASE_RULES,
    COMMON_PHRASE_RULES,
    SEC_COVER_PHRASE_RULES,
)
from defs.text import PhraseSequenceRule

if TYPE_CHECKING:
    from defs.tables.scope import TableScope


# --- Boundary phrase groups ---------------------------------------------------

COMMON_BOUNDARY_PHRASES: tuple[str, ...] = (
    "table of contents",
    "part i item 1",
)

ANNUAL_BOUNDARY_PHRASES: tuple[str, ...] = (
    *COMMON_BOUNDARY_PHRASES,
    "documents incorporated by reference",
)

NO_COVER_BOUNDARY_PHRASES: tuple[str, ...] = ()


# --- Label groups -------------------------------------------------------------

# Labels enabled for cover-candidate table detection. Annual and quarterly
# covers share the core identity/contact labels; annual adds nothing extra
# here because the annual-only anchors are phrase-healing rules, not labels.
COMMON_COVER_LABELS: tuple[str, ...] = tuple(
    term for values in COVER_LABELS.values() for term in values
)

ANNUAL_COVER_LABELS: tuple[str, ...] = COMMON_COVER_LABELS

QUARTERLY_COVER_LABELS: tuple[str, ...] = COMMON_COVER_LABELS

NO_COVER_LABELS: tuple[str, ...] = ()


# Extra evidence terms used alongside labels when marking cover-candidate
# tables. These are captions that have no dedicated label matcher yet.
_COVER_EVIDENCE_TERMS: tuple[str, ...] = (
    "section 12(b)",
    "accelerated filer",
    "shell company",
    "smaller reporting company",
    "emerging growth company",
)

QUARTERLY_PHRASE_RULES: tuple[PhraseSequenceRule, ...] = tuple(COMMON_PHRASE_RULES)

NO_COVER_PHRASE_RULES: tuple[PhraseSequenceRule, ...] = ()


@dataclass(frozen=True)
class CoverProfile:
    """Immutable, typed description of cover processing for one form family.

    Attributes:
        family: Canonical form family name (e.g. ``"10-K"``).
        eligible: Whether cover processing may run for this profile.
        table_scope: Table-scope capability used when applying templates to
            candidate tables.
        labels: Label terms used to mark cover-candidate tables.
        evidence_terms: Additional caption terms used for candidate detection.
        boundary_phrases: Phrases that delimit the cover healing region.
        phrase_rules: Phrase-healing rules enabled by this profile.
    """

    family: str
    eligible: bool
    table_scope: TableScope
    labels: tuple[str, ...]
    evidence_terms: tuple[str, ...]
    boundary_phrases: tuple[str, ...]
    phrase_rules: tuple[PhraseSequenceRule, ...]


def _make_profile(
    family: str,
    eligible: bool,
    table_scope: TableScope,
    labels: tuple[str, ...],
    boundary_phrases: tuple[str, ...],
    phrase_rules: tuple[PhraseSequenceRule, ...],
) -> CoverProfile:
    return CoverProfile(
        family=family,
        eligible=eligible,
        table_scope=table_scope,
        labels=labels,
        evidence_terms=_COVER_EVIDENCE_TERMS if eligible else (),
        boundary_phrases=boundary_phrases,
        phrase_rules=phrase_rules,
    )


def _build_profiles() -> dict[str, CoverProfile]:
    from defs.tables.templates import TableScope

    annual_common = _make_profile(
        family="10-K",
        eligible=True,
        table_scope=TableScope.COVER,
        labels=ANNUAL_COVER_LABELS,
        boundary_phrases=ANNUAL_BOUNDARY_PHRASES,
        phrase_rules=tuple(COMMON_PHRASE_RULES) + tuple(ANNUAL_ADDITIONAL_PHRASE_RULES),
    )
    annual_foreign = _dataclass_replace(annual_common, family="20-F")
    quarterly = _make_profile(
        family="10-Q",
        eligible=True,
        table_scope=TableScope.COVER,
        labels=QUARTERLY_COVER_LABELS,
        boundary_phrases=COMMON_BOUNDARY_PHRASES,
        phrase_rules=QUARTERLY_PHRASE_RULES,
    )
    no_cover_8k = _make_profile(
        family="8-K",
        eligible=False,
        table_scope=TableScope.BODY,
        labels=NO_COVER_LABELS,
        boundary_phrases=NO_COVER_BOUNDARY_PHRASES,
        phrase_rules=NO_COVER_PHRASE_RULES,
    )
    no_cover_6k = _dataclass_replace(no_cover_8k, family="6-K")
    generic = _make_profile(
        family="GENERIC",
        eligible=False,
        table_scope=TableScope.BODY,
        labels=NO_COVER_LABELS,
        boundary_phrases=NO_COVER_BOUNDARY_PHRASES,
        phrase_rules=NO_COVER_PHRASE_RULES,
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
    "ANNUAL_BOUNDARY_PHRASES",
    "ANNUAL_COVER_LABELS",
    "COMMON_BOUNDARY_PHRASES",
    "COMMON_COVER_LABELS",
    "COMMON_PHRASE_RULES",
    "COVER_PROFILES",
    "NO_COVER_BOUNDARY_PHRASES",
    "NO_COVER_LABELS",
    "NO_COVER_PHRASE_RULES",
    "QUARTERLY_COVER_LABELS",
    "QUARTERLY_PHRASE_RULES",
    "SEC_COVER_PHRASE_RULES",
    "CoverProfile",
    "get_profile",
]
