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
from edgar_sec.domain.forms.families.form144.processing import PROFILE_FORM_144
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
from edgar_sec.domain.forms.families.registration.checkmarks import (
    S1_CHECKBOX_SCHEMA,
    S3_CHECKBOX_SCHEMA,
    S4_CHECKBOX_SCHEMA,
    S8_CHECKBOX_SCHEMA,
)
from edgar_sec.domain.forms.families.registration.processing import (
    PROFILE_S1,
    PROFILE_S3,
    PROFILE_S4,
    PROFILE_S8,
)


from edgar_sec.domain.forms.common.models import ItemDefinition
from edgar_sec.domain.forms.families.annual.taxonomy import (
    FORM_10K_ITEMS,
    FORM_20F_ITEMS,
)
from edgar_sec.domain.forms.families.current.taxonomy import FORM_8K_ITEMS
from edgar_sec.domain.forms.families.quarterly.taxonomy import FORM_10Q_ITEMS
from edgar_sec.domain.forms.families.registration.taxonomy import (
    FORM_S1_ITEMS,
    FORM_S3_ITEMS,
    FORM_S4_ITEMS,
    FORM_S8_ITEMS,
)
from edgar_sec.domain.forms.families.beneficial_ownership.processing import (
    PROFILE_SCHEDULE_13D,
    PROFILE_SCHEDULE_13G,
)
from edgar_sec.domain.forms.families.beneficial_ownership.taxonomy import (
    SCHEDULE_13D_ITEMS,
    SCHEDULE_13G_ITEMS,
)


@dataclass(frozen=True, slots=True)
class ProcessingCatalogEntry:
    """Entry in the processing catalog."""

    family: str
    profile: DocumentProcessingProfile
    cover_checkbox_schema: CoverCheckboxSchema | None = None
    taxonomy_items: tuple[ItemDefinition, ...] = ()


FAMILY_PROCESSING_PROFILES: tuple[ProcessingCatalogEntry, ...] = (
    ProcessingCatalogEntry(
        family="10-K",
        profile=ANNUAL_PROFILE,
        cover_checkbox_schema=ANNUAL_CHECKBOX_SCHEMA,
        taxonomy_items=FORM_10K_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="20-F",
        profile=ANNUAL_PROFILE_20F,
        cover_checkbox_schema=ANNUAL_CHECKBOX_SCHEMA,
        taxonomy_items=FORM_20F_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="10-Q",
        profile=QUARTERLY_PROFILE,
        cover_checkbox_schema=QUARTERLY_CHECKBOX_SCHEMA,
        taxonomy_items=FORM_10Q_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="8-K",
        profile=CURRENT_PROFILE,
        cover_checkbox_schema=EIGHT_K_CHECKBOX_SCHEMA,
        taxonomy_items=FORM_8K_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="6-K",
        profile=CURRENT_PROFILE,
        cover_checkbox_schema=SIX_K_CHECKBOX_SCHEMA,
    ),
    ProcessingCatalogEntry(
        family="S-1",
        profile=PROFILE_S1,
        cover_checkbox_schema=S1_CHECKBOX_SCHEMA,
        taxonomy_items=FORM_S1_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="S-3",
        profile=PROFILE_S3,
        cover_checkbox_schema=S3_CHECKBOX_SCHEMA,
        taxonomy_items=FORM_S3_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="S-4",
        profile=PROFILE_S4,
        cover_checkbox_schema=S4_CHECKBOX_SCHEMA,
        taxonomy_items=FORM_S4_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="S-8",
        profile=PROFILE_S8,
        cover_checkbox_schema=S8_CHECKBOX_SCHEMA,
        taxonomy_items=FORM_S8_ITEMS,
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
    ProcessingCatalogEntry(
        family="144",
        profile=PROFILE_FORM_144,
    ),
    ProcessingCatalogEntry(
        family="13D",
        profile=PROFILE_SCHEDULE_13D,
        taxonomy_items=SCHEDULE_13D_ITEMS,
    ),
    ProcessingCatalogEntry(
        family="13G",
        profile=PROFILE_SCHEDULE_13G,
        taxonomy_items=SCHEDULE_13G_ITEMS,
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


LAZY_INDEX_FORM_FAMILIES: frozenset[str] = frozenset(
    {"10-K", "10-Q", "8-K", "20-F", "S-1", "S-3", "S-4", "S-8"}
)


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
