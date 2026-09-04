"""Representation-neutral document-context contracts.

These models describe per-block section context and per-table context for the
HTML table-conversion pipeline. They are deliberately form-name agnostic:
form-family profiles populate them, the shared table layer consumes them, and
no model contains a hard-coded SEC form name.

Design rules (from the table-processing context refactor plan):

- Every field is optional. Missing/unknown context is a valid state and must
  fall back to standalone table classification; it must not be replaced with
  an inferred false value.
- Context is *not* part of normalized table identity, canonical cell text, or
  expected rendering. It lives in separate provenance/classification
  evidence.
- Multiple logical regions with the same section name are valid. Context
  identifies a *region/locator*, not just an item label.
- The models are pure data + tiny factories; they do not import BeautifulSoup
  or perform I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from defs.tables.templates.scope import TableScope

__all__ = [
    "ContextEvidence",
    "ContextSource",
    "CoverScope",
    "FamilyClassification",
    "RepairPolicy",
    "SectionContext",
    "TableContext",
    "TableNode",
    "TocReference",
    "VocabularyEvidence",
]


class ContextSource(str, Enum):
    """How a context value was resolved.

    Used for review/provenance; downstream callers can fall back when the
    source is weak (e.g. ``form_fallback``).
    """

    BODY_HEADING = "body_heading"
    TOC_ANCHOR = "toc_anchor"
    TOC_TEXT_MATCH = "toc_text_match"
    FORM_FALLBACK = "form_fallback"
    UNKNOWN = "unknown"


from defs.taxonomy.tables.specs import (
    FamilyClassification,
    RepairPolicy,
    VocabularyEvidence,
)


@dataclass(frozen=True, slots=True)
class ContextEvidence:
    """A single piece of evidence supporting a context decision."""

    name: str
    strength: float = 0.0
    details: str = ""
    line: int | None = None


@dataclass(frozen=True, slots=True)
class TocReference:
    """One TOC entry linking a label to a body region.

    The HTML adapter may produce multiple TOC references per filing
    (main TOC, financial-statement index, note index, exhibit index). Each
    reference carries its provenance and a confidence, not a single global
    TOC span.
    """

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
    """Typed cover-scope result.

    This adapts the existing ``CoverBoundary`` plus the resolved
    :class:`defs.sec_forms.cover.profiles.CoverProfile` into a single
    representation-neutral value that the shared table layer can consume.
    An isolated cover table can receive an active cover scope and use cover
    BoW + cover templates without a full document.
    """

    active: bool
    profile_family: str
    confidence: float
    evidence: tuple[ContextEvidence, ...] = ()
    start_line: int | None = None
    end_line: int | None = None


@dataclass(frozen=True, slots=True)
class SectionContext:
    """Representation-neutral section context for one logical block.

    A logical block is a paragraph, list item, caption, validated heading, or
    a leaf div/span block. Section context is reused for paragraphs, lists,
    cover blocks, headings, and tables.
    """

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
    """A scanned table in the structure index.

    Carries its document ordinal, its parent table ordinal (for nested
    tables), and a stable locator independent of BeautifulSoup's
    ``sourceline`` (which is unreliable on the current lxml setup).
    """

    ordinal: int
    locator: str
    row_count: int
    cell_count: int
    parent_table_ordinal: int | None = None
    depth: int = 0


@dataclass(frozen=True, slots=True)
class TableContext:
    """Per-table context composed of optional section context + table-local metadata.

    Standalone callers (no document scan) use ``section=None``. The table-local
    classifier and safe repairs continue to run in that mode.
    """

    section: SectionContext | None = None
    table_ordinal: int = 0
    locator: str = ""
    caption_candidate: str | None = None
    header_features: tuple[str, ...] = ()
    body_features: tuple[str, ...] = ()
    table_shape_fingerprint: str | None = None
    evidence: tuple[ContextEvidence, ...] = field(default_factory=tuple)
