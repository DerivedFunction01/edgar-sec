"""Immutable page-marker models and the shape vocabulary detection is stated in.
A detection records the `kind` it matched, not a free-form reason, so policy is stated in the
vocabulary. Every coordinate stays in the declared `coordinate_frame`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.tokens import ROMAN_NUMERAL_PATTERN

#: A roman value is the shared numeral pattern, so `iv` and `IV` are one value under casefold.
PAGE_VALUE_ARABIC = r"\d{1,4}"
PAGE_VALUE = rf"(?:{PAGE_VALUE_ARABIC}|{ROMAN_NUMERAL_PATTERN})"
RE_PAGE_VALUE = re.compile(rf"{PAGE_VALUE}", re.IGNORECASE)

#: A wrapper is a glyph, not a character class: the dash family has three real members.
LABEL_WRAPPERS = build_alternation(
    ["-", "–", "—", ".", "·", "•", "▪"], auto_escape=True
)

#: Refused before any label shape: a heading that ends in a number is still a heading.
STRUCTURAL_HEADING = re.compile(
    rf"(?i)^(?:{build_alternation(['part', 'item', 'exhibit', 'note'], auto_escape=True)})\b"
)

#: `page N of M`, `N of M`, `page N`, `- N -`, `F-3`, and the SGML tag in line and inline forms.
#: Ordered: the first pattern matching an overlapping span claims it, so total-count shapes precede partial ones.
_PAGE_NUMBER_OF_TOTAL = re.compile(
    r"(?im)^[ \t]*page[ \t]+(?P<page>\d+)[ \t]+of[ \t]+(?P<count>\d+)[ \t]*$"
)
_NUMBER_OF_TOTAL = re.compile(
    r"(?im)^[ \t]*(?P<page>\d+)[ \t]+of[ \t]+(?P<count>\d+)[ \t]*$"
)
_PAGE_NUMBER = re.compile(r"(?im)^[ \t]*page[ \t]+(?P<page>\d+)[ \t]*$", re.IGNORECASE)
_DASHED_NUMBER = re.compile(r"(?im)^[ \t]*-[ \t]*(?P<page>\d+)[ \t]*-[ \t]*$")
LETTER_NUMBER_LABEL = re.compile(
    r"(?im)^\s*(?:page\s+)?(?P<prefix>[A-Z])\s*[-–—]\s*(?P<page>\d+)\s*[-–—]?\s*$"
)
_SGML_LINE = re.compile(
    r"(?im)^[ \t]*</?PAGE\b[^>]*>[ \t]*"
    r"(?P<page>(?:[A-Z](?:\s*[-–—]\s*\d+)?|\d+))?[ \t]*"
    r"(?:</?PAGE\b[^>]*>)?[ \t]*$"
)
_SGML_INLINE = re.compile(r"(?i)</?PAGE\b[^>]*>")

#: A boundary carries a page boundary and no value: the one firm shape with nothing to extract.
RE_BOUNDARY_TOKEN = re.compile(r"(?im)^[ \t]*(?:\(PAGE\)|\[PAGE\])[ \t]*$")

#: The arabic/roman namespace comes from the matched value, not the pattern, so one dash-wrapped
#: pattern keeps roman and arabic labels apart.
DASH_LABEL = re.compile(
    rf"^(?=.*(?:{LABEL_WRAPPERS}))(?:{LABEL_WRAPPERS}|\s)+"
    rf"(?P<value>{PAGE_VALUE})"
    rf"(?:{LABEL_WRAPPERS}|\s)+$",
    re.IGNORECASE,
)
PIPE_LABEL = re.compile(rf"^\|\s*(?P<value>{PAGE_VALUE})\s*\|$", re.IGNORECASE)
PAREN_LABEL = re.compile(rf"^\(\s*(?P<value>{PAGE_VALUE})\s*\)$", re.IGNORECASE)
SIMPLE_WRAPPED_LABEL = re.compile(
    rf"^(?:[|]\s*{PAGE_VALUE_ARABIC}\s*[|]"
    rf"|\(\s*{PAGE_VALUE_ARABIC}\s*\)"
    rf"|{PAGE_VALUE_ARABIC}\.)$"
)
DOTTED_LABEL = re.compile(rf"^(?P<value>{PAGE_VALUE_ARABIC})\.$")
BARE_ARABIC = re.compile(rf"^(?P<value>{PAGE_VALUE_ARABIC})$")
BARE_ROMAN = re.compile(rf"^(?P<value>{ROMAN_NUMERAL_PATTERN})$", re.IGNORECASE)
APPENDIX_ROMAN_LABEL = re.compile(
    rf"^(?P<prefix>[A-Za-z])-(?P<value>{ROMAN_NUMERAL_PATTERN})$",
    re.IGNORECASE,
)

#: A numbered paragraph and a line merely ending in a number look alike to a line reader, so each of
#: these three is length-bounded before acceptance.
LEADING_NUMBER_LABEL = re.compile(r"^(?P<value>\d{1,4})\s{1,}\S.*$")
TRAILING_NUMBER_LABEL = re.compile(r"^\S.*?\s{2,}(?P<value>\d{1,4})$")
PIPE_HEADER_NUMBER_LABEL = re.compile(
    r"^(?P<prefix>.*?[|]\s*)(?P<value>\d{1,4})$",
    re.IGNORECASE,
)
INLINE_PAGE_LABEL = re.compile(
    r"^(?P<prefix>.{0,80}?\bpage\s+)(?P<value>\d{1,4})\b(?P<suffix>.{0,80})$",
    re.IGNORECASE,
)


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


#: Firm shapes, in the order they claim an overlapping span. Each stands alone on its line and is
#: recognized by pattern alone; the contextual shapes above need a validated run before anything goes.
PAGE_MARKER_PATTERNS = (
    (PageMarkerKind.PAGE_NUMBER_OF_TOTAL, _PAGE_NUMBER_OF_TOTAL),
    (PageMarkerKind.NUMBER_OF_TOTAL, _NUMBER_OF_TOTAL),
    (PageMarkerKind.PAGE_NUMBER, _PAGE_NUMBER),
    (PageMarkerKind.DASHED_NUMBER, _DASHED_NUMBER),
    (PageMarkerKind.LETTER_NUMBER, LETTER_NUMBER_LABEL),
    (PageMarkerKind.SGML, _SGML_LINE),
    (PageMarkerKind.SGML, _SGML_INLINE),
)


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
class TemplateEvidence:
    """Evidence for a repeated header/footer template."""

    side: str
    position: int
    template: str
    occurrences: int
    presence: float
    kind: str
    lines: tuple[int, ...] = ()
    cohort_start_line: int | None = None
    cohort_end_line: int | None = None
    role: str = "unknown"
    retention: str = "preserve"


@dataclass(frozen=True, slots=True)
class PageBreakArtifact:
    """Provenance record for one rendered page artifact event.
    The rendered token carries only the assigned id; every payload attribute lives here.
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
    artifacts: tuple[PageBreakArtifact, ...] = ()
    rejection_diagnostics: tuple[str, ...] = ()


#: Words that legitimately occur in footer titles ("the", "of", "for", "to", "no", "which", "during") are
#: deliberately excluded; the rest reject prose-bearing lookalike tables such as footnotes and comparisons.
PROSE_GUARD_STOP_WORDS = frozenset(
    [
        "about",
        "above",
        "all",
        "also",
        "any",
        "because",
        "been",
        "being",
        "below",
        "both",
        "can",
        "could",
        "do",
        "does",
        "each",
        "had",
        "has",
        "have",
        "herein",
        "however",
        "is",
        "more",
        "most",
        "only",
        "over",
        "same",
        "should",
        "some",
        "such",
        "than",
        "there",
        "these",
        "this",
        "those",
        "through",
        "until",
        "was",
        "were",
        "when",
        "who",
        "will",
        "would",
        "see",
    ]
)

#: Compared after lowercasing, dropping every non-alphanumeric, and replacing digit runs with `#`, so
#: `page_1` and `page-break` collapse to one alias each without fuzzy matching. Only `break` splits a page.
PAGE_HINT_ROLES: dict[str, tuple[str, ...]] = {
    "pagebreak": ("break",),
    "ctpagebreak": ("break",),
    "pgbrk": ("break",),
    "pgbk": ("break",),
    "pagebreakbefore": ("break",),
    "pagebreakafter": ("break",),
    "breakbefore": ("break",),
    "breakafter": ("break",),
    "dspfpagebreak": ("break",),
    "dspfpagebreakarea": ("break",),
    "lastpagebreak": ("break",),
    "pgnum": ("number",),
    "pagenum": ("number",),
    "pagenumber": ("number",),
    "dspfpagenumber": ("number",),
    "dspfpagenumberarea": ("number",),
    "tocpgnum": ("number",),
    "acipg#": ("number",),
    "pghdr": ("header",),
    "pageheader": ("header",),
    "headercontainer": ("header",),
    "bclheader": ("header",),
    "pgftr": ("footer",),
    "pagefooter": ("footer",),
    "footercontainer": ("footer",),
    "bclfooter": ("footer",),
    "ctheaderfooterpage": ("header", "footer"),
    "page#": ("container",),
    "pagenodecontent": ("container",),
    "eolpage#": ("container",),
}


__all__ = [
    "APPENDIX_ROMAN_LABEL",
    "BARE_ARABIC",
    "BARE_ROMAN",
    "DASH_LABEL",
    "DOTTED_LABEL",
    "INLINE_PAGE_LABEL",
    "LABEL_WRAPPERS",
    "LEADING_NUMBER_LABEL",
    "LETTER_NUMBER_LABEL",
    "PAGE_HINT_ROLES",
    "PAGE_MARKER_PATTERNS",
    "PAGE_VALUE",
    "PAGE_VALUE_ARABIC",
    "PAREN_LABEL",
    "PIPE_HEADER_NUMBER_LABEL",
    "PIPE_LABEL",
    "PROSE_GUARD_STOP_WORDS",
    "RE_BOUNDARY_TOKEN",
    "RE_PAGE_VALUE",
    "SIMPLE_WRAPPED_LABEL",
    "STRUCTURAL_HEADING",
    "TRAILING_NUMBER_LABEL",
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
    "TemplateEvidence",
]
