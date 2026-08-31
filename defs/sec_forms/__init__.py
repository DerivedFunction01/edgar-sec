"""Shared SEC Form definitions, semantic concepts, checkmark decoders, and layout formatters."""

from __future__ import annotations

from defs.sec_forms.concepts import ConceptPattern
from defs.sec_forms.families import (
    FORM_FAMILY_ALIASES,
    aliases_for_family,
    form_family,
    normalize_form,
    resolve_alias,
)
from defs.sec_forms.models import (
    CheckboxDisclosures,
    CoverPageModel,
    RegistrantEntry,
    Security12b,
)
from defs.sec_forms.patterns import FILER_CATEGORY_PATTERNS
from defs.sec_forms.sequences import SEC_COVER_PHRASE_RULES
from defs.sec_forms.taxonomy import (
    FORM_8K_ITEMS,
    FORM_10K_ITEMS,
    FORM_10K_PARTS,
    FORM_10Q_ITEMS,
    FORM_10Q_PARTS,
)

__all__ = [
    "FILER_CATEGORY_PATTERNS",
    "FORM_8K_ITEMS",
    "FORM_10K_ITEMS",
    "FORM_10K_PARTS",
    "FORM_10Q_ITEMS",
    "FORM_10Q_PARTS",
    "FORM_FAMILY_ALIASES",
    "SEC_COVER_PHRASE_RULES",
    "CheckboxDisclosures",
    "ConceptPattern",
    "CoverPageModel",
    "RegistrantEntry",
    "Security12b",
    "aliases_for_family",
    "form_family",
    "normalize_form",
    "resolve_alias",
]
