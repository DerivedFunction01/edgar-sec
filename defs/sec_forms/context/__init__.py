"""Document-context contracts and adapters.

The package exposes a small set of representation-neutral dataclasses that
form-family profiles populate and the shared table-conversion layer
consumes. Adapters translate existing boundary, profile, and TOC types
into the new context models without introducing new detection logic.

Structure scanner:
- :func:`scan_html` builds an :class:`HtmlStructureIndex` from a
  BeautifulSoup tree in a single ``soup.descendants`` walk.
"""

from __future__ import annotations

from .adapters import (
    TocEntry,
    build_cover_scope,
    extract_toc_references,
    lift_toc_span_to_references,
)
from .models import (
    ContextEvidence,
    ContextSource,
    CoverScope,
    FamilyClassification,
    RepairPolicy,
    SectionContext,
    TableContext,
    TableNode,
    TocReference,
    VocabularyEvidence,
)
from .structure import (
    BlockNode,
    HeadingNode,
    HtmlStructureIndex,
    scan_html,
)

__all__ = [
    "BlockNode",
    "ContextEvidence",
    "ContextSource",
    "CoverScope",
    "FamilyClassification",
    "HeadingNode",
    "HtmlStructureIndex",
    "RepairPolicy",
    "SectionContext",
    "TableContext",
    "TableNode",
    "TocEntry",
    "TocReference",
    "VocabularyEvidence",
    "build_cover_scope",
    "extract_toc_references",
    "lift_toc_span_to_references",
    "scan_html",
]
