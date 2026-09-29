"""Canonical SEC form-family alias registry.

Single source of truth for mapping a raw form string to its canonical family.
The engine and every pipeline resolve families through this table; no consumer
owns a private alias list. Suffix stripping is applied before alias lookup so
``10-K405/A`` resolves the same way as ``10-K/A``.
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
        "10KT405",
        "10KT405/A",
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
# Order matters: each entry is removed at most once, so "10-K/A-POS" needs
# "-POS" removed before "/A".
FORM_FAMILY_SUFFIXES: tuple[str, ...] = (
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
    """Collapse amendment and submission suffixes into the base form family.

    ``10-K/A`` and ``10-K_A`` both become ``10-K``. A form that is *entirely*
    suffixes (``/A``) collapses to the empty string, and the original is
    returned rather than an empty dimension value.
    """
    base = form.upper().strip()
    for suffix in FORM_FAMILY_SUFFIXES:
        base = base.removesuffix(suffix)
    return base.strip("_-") or form


def resolve_alias(form: str | None) -> str | None:
    """Resolve a raw form string to its canonical family, or None if unknown."""
    if not form:
        return None
    direct = _ALIAS_LOOKUP.get(form.strip().upper())
    if direct is not None:
        return direct
    family = form_family(form)
    direct = _ALIAS_LOOKUP.get(family)
    if direct is not None:
        return direct
    return family if family in FORM_FAMILY_ALIASES else None


def normalize_form(form: str | None) -> str | None:
    """Return the canonical family for a raw form string, or None if unknown."""
    return resolve_alias(form)


def aliases_for_family(family: str) -> tuple[str, ...]:
    """Return the canonical alias tuple for a form family."""
    return FORM_FAMILY_ALIASES.get(family.upper(), ())


__all__ = [
    "FORM_FAMILY_ALIASES",
    "FORM_FAMILY_SUFFIXES",
    "aliases_for_family",
    "form_family",
    "normalize_form",
    "resolve_alias",
]
