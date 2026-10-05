"""Representation-neutral document-context contracts for table classification."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from edgar_sec.domain.taxonomy.tables.specs import TableScope


class ContextSource(str, Enum):
    """How a context value was resolved."""

    BODY_HEADING = "body_heading"
    TOC_ANCHOR = "toc_anchor"
    TOC_TEXT_MATCH = "toc_text_match"
    FORM_FALLBACK = "form_fallback"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ContextEvidence:
    """A single piece of evidence supporting a context decision."""

    name: str
    strength: float = 0.0
    details: str = ""
    line: int | None = None


@dataclass(frozen=True, slots=True)
class TocReference:
    """One TOC entry linking a label to a body region."""

    label: str
    normalized_label: str
    part: str | None
    item: str | None
    anchor: str | None
    ordinal: int
    confidence: float
    page: str | None = None
    evidence: tuple[ContextEvidence, ...] = ()


@dataclass(frozen=True, slots=True)
class CoverScope:
    """Typed cover-scope result."""

    active: bool
    profile_family: str
    confidence: float
    evidence: tuple[ContextEvidence, ...] = ()
    start_line: int | None = None
    end_line: int | None = None


@dataclass(frozen=True, slots=True)
class SectionContext:
    """Representation-neutral section context for one logical block."""

    document_id: str = ""
    source_sha256: str = ""
    form_family: str | None = None
    scope: TableScope = TableScope.BODY
    part: str | None = None
    item: str | None = None
    section_key: str | None = None
    heading: str | None = None
    heading_fingerprint: str | None = None
    preceding_blocks: tuple[str, ...] = ()
    following_blocks: tuple[str, ...] = ()
    toc_reference: TocReference | None = None
    cover_scope: CoverScope | None = None
    confidence: float = 0.0
    source: ContextSource = ContextSource.UNKNOWN
    evidence: tuple[ContextEvidence, ...] = ()
    processor_fingerprint: str = ""
    schema_version: str = "1"

    def is_unknown(self) -> bool:
        """True when no part/item/heading/toc fields are populated."""
        return (
            self.part is None
            and self.item is None
            and self.heading is None
            and self.toc_reference is None
        )


@dataclass(frozen=True, slots=True)
class TableNode:
    """A scanned table in the structure index."""

    ordinal: int
    locator: str
    row_count: int
    cell_count: int
    parent_table_ordinal: int | None = None
    depth: int = 0


@dataclass(frozen=True, slots=True)
class TableContext:
    """Per-table context composed of optional section context + table-local metadata."""

    section: SectionContext | None = None
    table_ordinal: int = 0
    locator: str = ""
    caption_candidate: str | None = None
    header_features: tuple[str, ...] = ()
    body_features: tuple[str, ...] = ()
    table_shape_fingerprint: str | None = None
    evidence: tuple[ContextEvidence, ...] = field(default_factory=tuple)


__all__ = [
    "ContextEvidence",
    "ContextSource",
    "CoverScope",
    "SectionContext",
    "TableContext",
    "TableNode",
    "TocReference",
]
