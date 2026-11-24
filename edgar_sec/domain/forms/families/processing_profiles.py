"""Processing profile catalog for form families.

Aggregates family declarations from annual/, quarterly/, and current/.
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.aliases import resolve_alias
from edgar_sec.domain.forms.common.processing import DocumentProcessingProfile
from edgar_sec.domain.forms.families.processing_catalog import (
    FAMILY_PROCESSING_PROFILES,
)
from edgar_sec.domain.forms.families.processing_profile_types import (
    ProcessingCatalogEntry,
)


_FAMILY_ENTRY_BY_FAMILY = {entry.family: entry for entry in FAMILY_PROCESSING_PROFILES}


def get_family_entry(family: str | None) -> ProcessingCatalogEntry | None:
    """Get catalog data for a canonical or aliased filing form."""
    if not family:
        return None
    normalized = resolve_alias(family) or family.strip().upper()
    return _FAMILY_ENTRY_BY_FAMILY.get(normalized)


def get_family_profile(family: str) -> DocumentProcessingProfile | None:
    """Get the processing profile for a given family.

    Returns None if the family has no registered profile.
    """
    entry = get_family_entry(family)
    return entry.profile if entry is not None else None


LAZY_INDEX_FORM_FAMILIES: frozenset[str] = frozenset(
    {
        "10-K",
        "10-Q",
        "8-K",
        "20-F",
        "S-1",
        "S-3",
        "S-4",
        "S-8",
        "3",
        "4",
        "5",
        "144",
        "D",
        "13D",
        "13G",
    }
)


def get_lazy_index_trigger(family: str | None) -> tuple[str, str] | None:
    """Return trigger ID and version for declared lazy-index families."""
    entry = get_family_entry(family)
    if entry is None or entry.family not in LAZY_INDEX_FORM_FAMILIES:
        return None
    return f"{entry.family}.exact_form", "1"


__all__ = [
    "LAZY_INDEX_FORM_FAMILIES",
    "get_family_entry",
    "get_family_profile",
    "get_lazy_index_trigger",
]
