"""Immutable page-marker models and the shape vocabulary detection is stated in.

A filing states its page structure in a small closed set of printed shapes: an
SGML `<PAGE>` tag, a bare or wrapped label, a `page N of M` line, a numeric
label that repeats at a fixed distance from its neighbours, and a block of text
that repeats at a fixed distance from every page anchor. Each shape gets a
stable `kind` name, and every detection records which shape it matched rather
than a free-form reason, so a downstream policy decision can be stated in terms
of the vocabulary instead of of one particular regex.

The models and the patterns are together because they are one vocabulary. A
`PageMarkerKind` name is not a label: `BARE_NUMBER` is only meaningful against
`BARE_ARABIC`, and `LETTER_NUMBER` against the namespaced form that can produce
an exhibit page. Everything below is stated in terms of the shared numeral and
alternation vocabulary rather than hand-rolled, so the same label shape is
recognized wherever it appears.

Every coordinate on every model is in the analysis's declared
`coordinate_frame`; nothing here interprets one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.tokens import ROMAN_NUMERAL_PATTERN

# --- The label shapes --------------------------------------------------------

#: An arabic page value: a short run of digits. A roman value is the shared
#: numeral pattern, so `iv` and `IV` are the same value under one casefold.
PAGE_VALUE_ARABIC = r"\d{1,4}"
PAGE_VALUE = rf"(?:{PAGE_VALUE_ARABIC}|{ROMAN_NUMERAL_PATTERN})"
RE_PAGE_VALUE = re.compile(rf"{PAGE_VALUE}", re.IGNORECASE)

#: The glyphs a printer wraps a page value in. A wrapper is a glyph, not a
#: character class, because the dash family has three members in real filings
#: and the interpunct and bullet forms appear in a fourth.
LABEL_WRAPPERS = build_alternation(
    ["-", "–", "—", ".", "·", "•", "▪"], auto_escape=True
)

#: Headings that open a document section. A heading that happens to end in a
#: number is still a heading, so these are refused before any label shape is
#: tried.
STRUCTURAL_HEADING = re.compile(
    rf"(?i)^(?:{build_alternation(['part', 'item', 'exhibit', 'note'], auto_escape=True)})\b"
)

#: `page N of M`, `N of M`, `page N`, `- N -`, `F-3`, and the SGML page tag in
#: both its line and inline forms. The tuple is ordered: the first pattern that
#: matches an overlapping span claims it, so the shapes carrying a total count
#: are listed before the ones that would match the same text partially.
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

#: A boundary token carries a page boundary and no page value, in either
#: bracketing convention. It is matched separately from the tuple below because
#: it is the one firm shape with nothing to extract.
RE_BOUNDARY_TOKEN = re.compile(r"(?im)^[ \t]*(?:\(PAGE\)|\[PAGE\])[ \t]*$")

#: The contextual label shapes. Each names a family in `PageMarkerKind`; the
#: arabic/roman namespace a shape lands in is decided from the matched value,
#: not from the pattern, so a dash-wrapped roman and a dash-wrapped arabic are
#: recognized by one pattern and kept apart by their values.
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

#: The three shapes that accept a line carrying other text. They are the
#: dangerous ones — a numbered paragraph and a line that merely ends in a
#: number look the same to a line-level reader — so each is length-bounded
#: before it is accepted.
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


# --- The models --------------------------------------------------------------


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


#: The firm shapes, in the order they claim an overlapping span. A firm shape
#: stands alone on its line and is recognized by pattern alone; the contextual
#: shapes above need a validated run before anything is removed.
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
    artifacts: tuple[PageBreakArtifact, ...] = ()
    rejection_diagnostics: tuple[str, ...] = ()


# Function words that empirically never appear in captured page header/footer
# text. Derived by probing all 2,202 ASCII fixtures: corpus of captured
# REPEATING_HEADER/REPEATING_FOOTER marker text versus sampled body lines
# (footer document-frequency == 0, body document-frequency >= 25%). Words that
# legitimately occur in footer titles ("the", "of", "for", "to", "no",
# "which", "during", "must") are deliberately excluded. Used to reject
# prose-bearing lookalike tables (footnote tables, comparison tables).
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

# HTML page-hint vocabulary: a filing generator names its own page furniture in
# `class`/`id`/CSS vocabulary, and the same generator reuses that name on every
# page. Entries are compared after lowercasing, dropping every non-alphanumeric
# character, and replacing digit runs with `#`, so `page_1`, `page_2`, and
# `page-break` collapse to one alias each (`page#`, `pagebreak`) without
# per-character fuzzy matching. Roles: `break`, `number`, `header`, `footer`,
# `container`. The `break` subset is the one that substitutes a page-split
# sentinel during projection, and lives in
# :data:`edgar_sec.engine.document.html.breaks.PAGE_BREAK_HINT_TOKENS`.
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
