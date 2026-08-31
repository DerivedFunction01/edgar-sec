"""Canonical SEC form-family alias registry and cover profile mapping.

This module is the single source of truth for form aliases, suffix-stripping
normalization, and the mapping from a normalized form family to a cover
profile. Phase 2.5 and future phases consume it; no phase owns aliases.
"""

from __future__ import annotations

# Canonical aliases grouped by form family. Amendment and submission suffixes
# are included explicitly so callers can map raw form strings directly.
FORM_FAMILY_ALIASES: dict[str, tuple[str, ...]] = {
    "10-K": (
        "10-K",
        "10-K/A",
        "10-K405",
        "10-K405/A",
        "10-KSB",
        "10-KSB/A",
        "10KSB",
        "10KSB40",
        "10-KT",
        "10-KT/A",
    ),
    "10-Q": (
        "10-Q",
        "10-Q/A",
        "10-QSB",
        "10-QSB/A",
        "10QSB",
        "10-QT",
        "10-QT/A",
    ),
    "8-K": (
        "8-K",
        "8-K/A",
        "8-K12B",
        "8-K12G3",
        "8-K15D5",
    ),
    "20-F": (
        "20-F",
        "20-F/A",
        "20FR12B",
        "20FR12G3",
    ),
    "6-K": (
        "6-K",
        "6-K/A",
    ),
}

# Suffixes stripped when collapsing a raw form string to its base family.
_FORM_SUFFIXES: tuple[str, ...] = (
    "_A",
    "_W",
    "_POS",
    "-POS",
    "MEF",
    "-W",
    "/A",
)


def _build_alias_lookup() -> dict[str, str]:
    lookup: dict[str, str] = {}
    for family, aliases in FORM_FAMILY_ALIASES.items():
        for alias in aliases:
            lookup[alias.upper()] = family
    return lookup


_ALIAS_LOOKUP: dict[str, str] = _build_alias_lookup()


def form_family(form: str) -> str:
    """Collapse amendment and submission suffixes into the base form family."""
    base = form.upper().strip()
    for suffix in _FORM_SUFFIXES:
        base = base.removesuffix(suffix)
    return base.strip("_-") or form


def normalize_form(form: str | None) -> str | None:
    """Return the canonical family for a raw form string, or None if unknown."""
    if not form:
        return None
    family = form_family(form)
    return family if family in FORM_FAMILY_ALIASES else None


def aliases_for_family(family: str) -> tuple[str, ...]:
    """Return the canonical alias tuple for a form family."""
    return FORM_FAMILY_ALIASES.get(family.upper(), ())


def resolve_alias(form: str | None) -> str | None:
    """Resolve a raw form string to its canonical family, or None if unknown."""
    if not form:
        return None
    direct = _ALIAS_LOOKUP.get(form.strip().upper())
    if direct is not None:
        return direct
    family = form_family(form)
    return family if family in FORM_FAMILY_ALIASES else None


def family_lookup(form: str | None) -> str | None:
    """Alias for :func:`resolve_alias` used by callers that prefer lookup wording."""
    return resolve_alias(form)


__all__ = [
    "FORM_FAMILY_ALIASES",
    "aliases_for_family",
    "family_lookup",
    "form_family",
    "normalize_form",
    "resolve_alias",
]
