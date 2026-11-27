"""Per-intent none-value vocabularies for the forms plane.

Memberships are per-intent and are not to be unified: each set is the
priced vocabulary of its consuming surface.
"""

from __future__ import annotations


EMPTY_CONTINUATION_WORDS: frozenset[str] = frozenset(
    {"none", "n/a", "no reported", "not applicable", "nil", "0"}
)


GENERIC_NONE_MARKERS: frozenset[str] = frozenset({"none", "not applicable", "n/a"})


FORM144_COVER_NONE_MARKERS: frozenset[str] = frozenset({"none", "n/a", "no", "nil"})


FORM144_SECTION_NONE_MARKERS: frozenset[str] = frozenset(
    {"n/a", "none", "no reported"}
)


FORM144_SECURITY_NONE_TERMS: tuple[str, ...] = (
    "none",
    "n/a",
    "no reported",
    "nothing to report",
)


FORM144_SECURITY_NONE_MARKERS: frozenset[str] = frozenset(
    {"none", "n/a", "na", "nil", "not applicable", "no"}
)


NOT_APPLICABLE_13G_TERMS: tuple[str, ...] = (
    "not applicable",
    "not-applicable",
    "item not applicable",
    "n/a",
    "none",
)


__all__ = [
    "EMPTY_CONTINUATION_WORDS",
    "FORM144_COVER_NONE_MARKERS",
    "FORM144_SECTION_NONE_MARKERS",
    "FORM144_SECURITY_NONE_MARKERS",
    "FORM144_SECURITY_NONE_TERMS",
    "GENERIC_NONE_MARKERS",
    "NOT_APPLICABLE_13G_TERMS",
]
