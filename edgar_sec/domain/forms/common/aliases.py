"""Canonical SEC form-family alias registry and suffix collapse.

Single source of truth for mapping a raw form string to its canonical family; suffix
stripping runs before alias lookup.
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
        "10KSB/A",
        "10KSB40",
        "10KSB40/A",
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
        "10QSB/A",
        "10-QT",
        "10-QT/A",
    ),
    "8-K": (
        "8-K",
        "8-K/A",
        "8-K12B",
        "8-K12B/A",
        "8-K12G3",
        "8-K12G3/A",
        "8-K15D5",
        "8-K15D5/A",
    ),
    "20-F": (
        "20-F",
        "20-F/A",
        "20FR12B",
        "20FR12B/A",
        "20FR12G",
        "20FR12G/A",
        "20FR12G3",
    ),
    "6-K": (
        "6-K",
        "6-K/A",
    ),
    "3": (
        "3",
        "3/A",
    ),
    "4": (
        "4",
        "4/A",
    ),
    "5": (
        "5",
        "5/A",
    ),
    "144": (
        "144",
        "144/A",
    ),
    "D": (
        "D",
        "D/A",
        "REGDEX",
        "REGDEX/A",
    ),
    "13F": (
        "13F",
        "13F/A",
        "13F-HR",
        "13F-HR/A",
        "13F-NT",
        "13F-NT/A",
        "13F-E",
        "13F-E/A",
        "13FCONP",
        "13FCONP/A",
    ),
    "13D": (
        "13D",
        "13D/A",
        "SC 13D",
        "SC 13D/A",
        "SCHEDULE 13D",
        "SCHEDULE 13D/A",
    ),
    "13G": (
        "13G",
        "13G/A",
        "SC 13G",
        "SC 13G/A",
        "SCHEDULE 13G",
        "SCHEDULE 13G/A",
    ),
    "S-1": (
        "S-1",
        "S-1/A",
        "S-1MEF",
        "S-1MEF/A",
        "S-1POS",
        "S-1/A-POS",
    ),
    "S-3": (
        "S-3",
        "S-3/A",
        "S-3ASR",
        "S-3D",
        "S-3D/A",
        "S-3DPOS",
        "S-3MEF",
    ),
    "S-4": (
        "S-4",
        "S-4 POS",
        "S-4/A",
        "S-4EF",
        "S-4EF/A",
        "S-4MEF",
    ),
    "S-8": (
        "S-8",
        "S-8 POS",
        "S-8/A",
    ),
    "14A": (
        "14A",
        "14A/A",
        "DEF 14A",
        "DEF 14C",
        "DEFA14A",
        "DEFA14C",
        "DEFC14A",
        "DEFC14C",
        "DEFM14A",
        "DEFM14C",
        "DEFN14A",
        "DEFR14A",
        "DEFR14C",
        "DEFS14A",
        "DEFS14C",
        "PRE 14A",
        "PRE 14C",
        "PREA14A",
        "PREC14A",
        "PREC14C",
        "PREM14A",
        "PREM14C",
        "PREN14A",
        "PRER14A",
        "PRER14C",
        "PRES14A",
        "PRES14C",
        "PRRN14A",
        "DFAN14A",
        "DFRN14A",
        "PX14A6G",
        "PX14A6N",
    ),
    "12B-25": (
        "12B-25",
        "12B-25/A",
        "NT 10-K",
        "NT 10-K/A",
        "NT 10-Q",
        "NT 10-Q/A",
        "NT 20-F",
        "NT 20-F/A",
        "NT 11-K",
        "NT 11-K/A",
        "NT 15D2/A",
        "NT N-CEN",
        "NT NPORT-EX",
        "NT NPORT-P",
        "NT-NCEN",
        "NT-NCSR",
        "NT-NCSR/A",
        "NT-NSAR",
        "NT-NSAR/A",
        "NTFNCEN",
        "NTFNCSR",
        "NTFNSAR",
        "NTN 10K",
        "NTN 10Q",
        "NTN 11K",
        "NTN 20F",
    ),
    "15": (
        "15",
        "15/A",
        "15-12B",
        "15-12B/A",
        "15-12G",
        "15-12G/A",
        "15-15D",
        "15-15D/A",
        "15F-12B",
        "15F-12G",
        "15F-12G/A",
        "15F-15D",
        "15F-15D/A",
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

    A form that is *entirely* suffixes (``/A``) returns the original, not an empty string.
    """
    form_str = str(form)
    base = form_str.upper().strip()
    for suffix in FORM_FAMILY_SUFFIXES:
        base = base.removesuffix(suffix)
    return base.strip("_-") or form_str


def resolve_alias(form: str | None) -> str | None:
    """Resolve a raw form string to its canonical family, or None if unknown."""
    if not form:
        return None
    form_str = str(form).strip().upper()
    direct = _ALIAS_LOOKUP.get(form_str)
    if direct is not None:
        return direct
    family = form_family(form_str)
    direct = _ALIAS_LOOKUP.get(family)
    if direct is not None:
        return direct
    return family if family in FORM_FAMILY_ALIASES else None


def aliases_for_family(family: str) -> tuple[str, ...]:
    """Return the canonical alias tuple for a form family."""
    return FORM_FAMILY_ALIASES.get(str(family).upper(), ())


__all__ = [
    "FORM_FAMILY_ALIASES",
    "FORM_FAMILY_SUFFIXES",
    "aliases_for_family",
    "form_family",
    "resolve_alias",
]
