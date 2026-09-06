"""Immutable models for ASCII page-marker analysis."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PageMarkerKind:
    """Stable names for supported page-marker and presentation shapes."""

    SGML = "sgml"
    DASHED_NUMBER = "dashed_number"
    PAGE_NUMBER = "page_number"
    NUMBER_OF_TOTAL = "number_of_total"
    PAGE_NUMBER_OF_TOTAL = "page_number_of_total"
    LETTER_NUMBER = "letter_number"
    APPENDIX_ROMAN = "appendix_roman"
    BARE_NUMBER = "bare_number"
    ROMAN_NUMBER = "roman_number"
    PIPE_NUMBER = "pipe_number"
    PAREN_NUMBER = "paren_number"
    DOTTED_NUMBER = "dotted_number"
    NUMBER_FIRST = "number_first"
    TRAILING_NUMBER = "trailing_number"
    INLINE_PAGE_NUMBER = "inline_page_number"
    BOUNDARY = "boundary"
    HTML_NODE = "html_node"
    TABLE_FOOTER = "table_footer"
    REPEATING_HEADER = "repeating_header"
    REPEATING_FOOTER = "repeating_footer"


class PageMarkerAction(StrEnum):
    """Decision actions for page-marker post-processing."""

    REMOVE = "remove"
    NORMALIZE = "normalize"
    PRESERVE = "preserve"


class PageMarkerTerminalState(StrEnum):
    """Explicit terminal outcomes for a page-marker analysis."""

    NONE = "none"
    NO_VISIBLE_LABELS = "no_visible_labels"
    UNRESOLVED = "unresolved"


class PageArtifactPolicy(StrEnum):
    """Rendering policy for validated page furniture."""

    STRIP = "strip"
    ANNOTATE = "annotate"
    PRESERVE = "preserve"


@dataclass(frozen=True, slots=True)
class PageMarkerSpan:
    """A detected page marker and its source span."""

    start: int
    end: int
    text: str
    kind: str
    page_number: int | None = None
    page_count: int | None = None
    coordinate_frame: str = "text"


@dataclass(frozen=True, slots=True)
class PageCandidate:
    """A candidate label found during an ASCII contextual scan."""

    start: int
    end: int
    start_line: int
    end_line: int
    text: str
    family: str
    namespace: str
    value: int
    relative_position: int | None = None
    leading_column: int = 0
    template: str = ""
    exclusion: str = ""
    coordinate_frame: str = "text"
    node_path: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class PageNumberRun:
    """One independently validated observed page-number run."""

    family: str
    namespace: str
    candidates: tuple[PageCandidate, ...]
    monotone_fraction: float
    gap_mean: float
    gap_median: float
    alignment_fraction: float
    source_start_line: int
    source_end_line: int
    strategy: str


@dataclass(frozen=True, slots=True)
class InferredBoundary:
    """Metadata-only page boundary with no removable source span."""

    line: float
    page_number: int | None
    namespace: str
    reason: str


@dataclass(frozen=True, slots=True)
class PageRegionReport:
    """Classification of one source interval outside validated page families.

    ``status`` is one of ``referential_labels`` (label-shaped tokens exist but
    no family claimed the region, e.g. a table of contents), ``weak_numeric``
    (bare digits only, typically financial tables), or ``likely_pageless``.
    Reports are metadata only and never authorize removal.
    """

    start_offset: int
    end_offset: int
    status: str
    letter_tokens: int = 0
    page_tokens: int = 0
    digit_tokens: int = 0


@dataclass(frozen=True, slots=True)
class TemplateEvidence:
    """Evidence for a repeated header/footer template."""

    side: str
    position: int
    template: str
    occurrences: int
    presence: float
    kind: str
    lines: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class PageBreakArtifact:
    """Provenance record for one rendered page artifact event.

    ``source`` names the validated origin (for example ``page_number``,
    ``hr``, ``page-break-container``, ``inferred-line``); coordinates stay in
    their declared ``coordinate_frame``. The rendered token carries only the
    assigned id; every payload attribute lives here.
    """

    page_number: int | str | None
    namespace: str | None
    source: str
    coordinate_frame: str
    source_identity: str
    node_path: tuple[int, ...] = ()
    start: int | None = None
    end: int | None = None
    start_line: int | None = None
    end_line: int | None = None
    removable: bool = False
    template_id: str | None = None


@dataclass(frozen=True, slots=True)
class PageMarker:
    """A detected page marker and its representation metadata."""

    start: int
    end: int
    text: str
    kind: str
    page_number: int | None = None
    page_count: int | None = None
    representation: str = "ascii"
    confidence: float = 1.0
    start_line: int | None = None
    end_line: int | None = None
    namespace: str = ""
    family: str = ""
    evidence: tuple[str, ...] = ()
    coordinate_frame: str = "text"
    node_path: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class PageMarkerDecision:
    """Action decision for a detected page marker."""

    marker: PageMarker
    action: PageMarkerAction
    reason: str
    confidence: float = 1.0
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PageMarkerAnalysis:
    """Complete immutable analysis in one declared source coordinate frame."""

    markers: tuple[PageMarker, ...]
    decisions: tuple[PageMarkerDecision, ...]
    page_boundaries: tuple[int, ...]
    representation: str = "ascii"
    source_text: str = ""
    source_identity: str = ""
    occupied_lines: tuple[int, ...] = ()
    page_number_runs: tuple[PageNumberRun, ...] = ()
    header_footer_templates: tuple[TemplateEvidence, ...] = ()
    inferred_boundaries: tuple[InferredBoundary, ...] = ()
    unresolved: tuple[str, ...] = ()
    terminal_state: PageMarkerTerminalState = PageMarkerTerminalState.NONE
    coordinate_frame: str = "text"
    regions: tuple[PageRegionReport, ...] = ()
    artifacts: tuple[PageBreakArtifact, ...] = ()


__all__ = [
    "InferredBoundary",
    "PageArtifactPolicy",
    "PageBreakArtifact",
    "PageCandidate",
    "PageMarker",
    "PageMarkerAction",
    "PageMarkerAnalysis",
    "PageMarkerDecision",
    "PageMarkerKind",
    "PageMarkerSpan",
    "PageMarkerTerminalState",
    "PageNumberRun",
    "PageRegionReport",
    "TemplateEvidence",
]
