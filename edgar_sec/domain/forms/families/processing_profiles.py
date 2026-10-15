"""Processing profile catalog for form families.

Aggregates family declarations from annual/, quarterly/, and current/.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.common.aliases import resolve_alias
from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DocumentProcessingProfile,
)
from edgar_sec.domain.forms.common.schemas import CoverCheckboxSchema
from edgar_sec.domain.forms.families.annual.processing import (
    PROFILE as ANNUAL_PROFILE,
    PROFILE_20F as ANNUAL_PROFILE_20F,
)
from edgar_sec.domain.forms.families.annual.checkmarks import ANNUAL_CHECKBOX_SCHEMA
from edgar_sec.domain.forms.families.current.checkmarks import (
    EIGHT_K_CHECKBOX_SCHEMA,
    SIX_K_CHECKBOX_SCHEMA,
)
from edgar_sec.domain.forms.families.current.processing import (
    PROFILE as CURRENT_PROFILE,
)
from edgar_sec.domain.forms.families.ownership.processing import (
    PROFILE_FORM_3,
    PROFILE_FORM_4,
    PROFILE_FORM_5,
)
from edgar_sec.domain.forms.families.quarterly.checkmarks import (
    QUARTERLY_CHECKBOX_SCHEMA,
)
from edgar_sec.domain.forms.families.quarterly.processing import (
    PROFILE as QUARTERLY_PROFILE,
)


@dataclass(frozen=True, slots=True)
class ProcessingCatalogEntry:
    """Entry in the processing catalog."""

    family: str
    profile: DocumentProcessingProfile
    cover_checkbox_schema: CoverCheckboxSchema | None = None


FAMILY_PROCESSING_PROFILES: tuple[ProcessingCatalogEntry, ...] = (
    ProcessingCatalogEntry(
        family="10-K",
        profile=ANNUAL_PROFILE,
        cover_checkbox_schema=ANNUAL_CHECKBOX_SCHEMA,
    ),
    ProcessingCatalogEntry(
        family="20-F",
        profile=ANNUAL_PROFILE_20F,
        cover_checkbox_schema=ANNUAL_CHECKBOX_SCHEMA,
    ),
    ProcessingCatalogEntry(
        family="10-Q",
        profile=QUARTERLY_PROFILE,
        cover_checkbox_schema=QUARTERLY_CHECKBOX_SCHEMA,
    ),
    ProcessingCatalogEntry(
        family="8-K",
        profile=CURRENT_PROFILE,
        cover_checkbox_schema=EIGHT_K_CHECKBOX_SCHEMA,
    ),
    ProcessingCatalogEntry(
        family="6-K",
        profile=CURRENT_PROFILE,
        cover_checkbox_schema=SIX_K_CHECKBOX_SCHEMA,
    ),
    ProcessingCatalogEntry(
        family="3",
        profile=PROFILE_FORM_3,
    ),
    ProcessingCatalogEntry(
        family="4",
        profile=PROFILE_FORM_4,
    ),
    ProcessingCatalogEntry(
        family="5",
        profile=PROFILE_FORM_5,
    ),
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


LAZY_INDEX_FORM_FAMILIES: frozenset[str] = frozenset({"10-K", "10-Q", "8-K", "20-F"})


def get_lazy_index_trigger(family: str | None) -> tuple[str, str] | None:
    """Return trigger ID and version for declared lazy-index families."""
    entry = get_family_entry(family)
    if entry is None or entry.family not in LAZY_INDEX_FORM_FAMILIES:
        return None
    return f"{entry.family}.exact_form", "1"


__all__ = [
    "FAMILY_PROCESSING_PROFILES",
    "LAZY_INDEX_FORM_FAMILIES",
    "ANNUAL_PROFILE",
    "QUARTERLY_PROFILE",
    "CURRENT_PROFILE",
    "ProcessingCatalogEntry",
    "get_family_entry",
    "get_family_profile",
    "get_lazy_index_trigger",
]
