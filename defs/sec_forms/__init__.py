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
from defs.sec_forms.forms.annual import (
    ITEMS as FORM_10K_ITEMS,
)
from defs.sec_forms.forms.annual import (
    PARTS as FORM_10K_PARTS,
)
from defs.sec_forms.forms.current_report import (
    ITEMS as FORM_8K_ITEMS,
)
from defs.sec_forms.forms.quarterly import (
    ITEMS as FORM_10Q_ITEMS,
)
from defs.sec_forms.forms.quarterly import (
    PARTS as FORM_10Q_PARTS,
)
from defs.sec_forms.models import (
    CheckboxDisclosures,
    CoverPageModel,
    RegistrantEntry,
    Security12b,
)
from defs.sec_forms.page_markers import (
    PageMarker,
    PageMarkerAction,
    PageMarkerAnalysis,
    PageMarkerDecision,
    PageMarkerKind,
    PageMarkerSpan,
    analyze_page_markers,
    find_page_markers,
    strip_page_markers,
)
from defs.sec_forms.sequences import SEC_COVER_PHRASE_RULES
from defs.sec_forms.vocabulary import (
    COVER_EVIDENCE_TERMS,
    COVER_LABELS,
    COVER_LABELS_FLAT,
    COVER_START_IDENTITY_TERMS,
    COVER_START_SHAPE_TERMS,
    FILER_CATEGORY_PATTERNS,
    SEC_HEADER_TERMS,
)

__all__ = [
    "COVER_EVIDENCE_TERMS",
    "COVER_LABELS",
    "COVER_LABELS_FLAT",
    "COVER_START_IDENTITY_TERMS",
    "COVER_START_SHAPE_TERMS",
    "FILER_CATEGORY_PATTERNS",
    "FORM_8K_ITEMS",
    "FORM_10K_ITEMS",
    "FORM_10K_PARTS",
    "FORM_10Q_ITEMS",
    "FORM_10Q_PARTS",
    "FORM_FAMILY_ALIASES",
    "SEC_COVER_PHRASE_RULES",
    "SEC_HEADER_TERMS",
    "CheckboxDisclosures",
    "ConceptPattern",
    "CoverPageModel",
    "PageMarker",
    "PageMarkerAction",
    "PageMarkerAnalysis",
    "PageMarkerDecision",
    "PageMarkerKind",
    "PageMarkerSpan",
    "RegistrantEntry",
    "Security12b",
    "aliases_for_family",
    "analyze_page_markers",
    "find_page_markers",
    "form_family",
    "normalize_form",
    "resolve_alias",
    "strip_page_markers",
]
