"""Catalog entry type for the processing profile catalog."""

from __future__ import annotations

from dataclasses import dataclass
from edgar_sec.domain.forms.common.processing import DocumentProcessingProfile
from edgar_sec.domain.forms.common.schemas import CoverCheckboxSchema
from edgar_sec.domain.forms.common.models import ItemDefinition


@dataclass(frozen=True, slots=True)
class ProcessingCatalogEntry:
    """Entry in the processing catalog."""

    family: str
    profile: DocumentProcessingProfile
    cover_checkbox_schema: CoverCheckboxSchema | None = None
    taxonomy_items: tuple[ItemDefinition, ...] = ()
