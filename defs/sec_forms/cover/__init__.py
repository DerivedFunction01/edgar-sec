"""Shared SEC cover-page concept registries, extraction primitives, and profiles."""

from __future__ import annotations

from defs.sec_forms.cover.body_start import find_body_start
from defs.sec_forms.cover.boundary import (
    find_cover_boundary,
    find_cover_boundary_for_profile,
    resolve_document_topology,
)
from defs.sec_forms.cover.closing import ClosingSpan, find_closing_span
from defs.sec_forms.cover.cover_start import find_cover_start
from defs.sec_forms.cover.extractors import (
    extract_candidate_ein,
    extract_commission_file_number,
    extract_fiscal_period,
)
from defs.sec_forms.cover.models import (
    BodyAnchorType,
    BodyRoot,
    BodyStart,
    BodyStartEvidence,
    BoundaryEvidence,
    BoundaryInput,
    BoundaryMethod,
    BoundarySignal,
    CoverBoundary,
    CoverBoundaryPolicy,
    CoverStart,
    DocumentTopology,
    ItemDefinition,
)
from defs.sec_forms.cover.structure import (
    RE_PART,
    RE_PART_ONE,
    ParsedSection,
    SectionKind,
    StructuralMatch,
    StructuralRole,
    is_continuation_prose,
    is_exact_heading,
    match_structural_line,
    parse_section_heading,
)
from defs.sec_forms.cover.toc import (
    RE_TOC_HEADING,
    RE_TOC_ITEM,
    RE_TOC_PART_TEXT,
    TocEvidence,
    TocSpan,
    find_toc_span,
    is_toc_row,
)
from defs.sec_forms.page_markers import (
    PageMarkerKind,
    PageMarkerSpan,
    find_page_markers,
)
from defs.sec_forms.vocabulary import COVER_LABELS

__all__ = [
    "COVER_LABELS",
    "COVER_PROFILES",
    "RE_PART",
    "RE_PART_ONE",
    "RE_TOC_HEADING",
    "RE_TOC_ITEM",
    "RE_TOC_PART_TEXT",
    "BodyAnchorType",
    "BodyRoot",
    "BodyStart",
    "BodyStartEvidence",
    "BoundaryEvidence",
    "BoundaryInput",
    "BoundaryMethod",
    "BoundarySignal",
    "ClosingSpan",
    "CoverBoundary",
    "CoverBoundaryPolicy",
    "CoverProfile",
    "CoverStart",
    "DocumentTopology",
    "ItemDefinition",
    "PageMarkerKind",
    "PageMarkerSpan",
    "ParsedSection",
    "SectionKind",
    "StructuralMatch",
    "StructuralRole",
    "TocEvidence",
    "TocSpan",
    "extract_candidate_ein",
    "extract_commission_file_number",
    "extract_fiscal_period",
    "find_body_start",
    "find_closing_span",
    "find_cover_boundary",
    "find_cover_boundary_for_profile",
    "find_cover_start",
    "find_page_markers",
    "find_toc_span",
    "get_profile",
    "is_continuation_prose",
    "is_exact_heading",
    "is_toc_row",
    "match_structural_line",
    "parse_section_heading",
    "resolve_document_topology",
]


def __getattr__(name: str):
    # Profile construction touches ``defs.tables`` (typed scope), which in turn
    # touches ``defs.sec_forms.vocabulary``. Loading it lazily here avoids a
    # circular import during ``defs.sec_forms`` package initialization.
    if name in {"COVER_PROFILES", "CoverProfile", "get_profile"}:
        from defs.sec_forms.cover import profiles as _profiles

        value = getattr(_profiles, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
