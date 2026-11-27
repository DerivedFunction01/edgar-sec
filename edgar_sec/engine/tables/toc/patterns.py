"""Table-of-contents and section-reference patterns.
The one home for the PART/ITEM/NOTE reference vocabulary: contents rows, headings,
grouped lists, captions, and cross-reference cues, so every consumer shares one definition.
"""

from __future__ import annotations

import re

from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.patterns import (
    ITEM_REFERENCE_CORE,
    PAGE_NUMBER_CORE,
    PART_REFERENCE_CORE,
    RE_DOT_LEADER,
)

RE_PART_REFERENCE = re.compile(
    rf"\b{PART_REFERENCE_CORE}(?:[IVXLCDM]+|\d+)\b", re.IGNORECASE
)
RE_ITEM_REFERENCE = re.compile(
    rf"\b{ITEM_REFERENCE_CORE}(?:\.\d+)*[A-Z]?\b", re.IGNORECASE
)
RE_NOTE_REFERENCE = re.compile(r"\bNOTES?\s+\d+(?:\.\d+)*[A-Z]?\b", re.IGNORECASE)

RE_TOC_ITEM_ROW = re.compile(
    r"^\s*(?:[\|+]\s*)?ITEMS?\s+(\d{1,2})([A-Z])?\b", re.IGNORECASE
)
RE_TOC_LEADER = re.compile(rf"\s{RE_DOT_LEADER.pattern}\s")

RE_PAGE_SUFFIX = re.compile(
    rf"(?:\b[A-Z])?[\.\-\s]?{PAGE_NUMBER_CORE}(?:\s*[\|+])?\s*$",
    re.IGNORECASE,
)

# A TOC row listing one or more items, closed by a dot or a space: the
# cover-TOC form of the item reference, distinct from the single-item row.
_TOC_ITEM_CONJUNCTION = build_alternation(["and", "&", "-"], auto_escape=True)
RE_TOC_ITEM = re.compile(
    rf"^\s*(?:[\|+]\s*)?ITEMS?\s+\d+[A-Z]?(?:[\s,]+(?:{_TOC_ITEM_CONJUNCTION})?[\s,]*\d+[A-Z]?)*[\.\s]",
    re.IGNORECASE,
)

# Anchored heading forms: a line-leading keyword and number, an optional
# separator, an optional "(continued)" marker, and the captured title tail.
RE_NOTE_HEADING = re.compile(
    r"^\s*(?:[\|+•\t-]\s*)?NOTES?\s+(\d+)\b(?:\s*[:.\-]\s*|\s+)?(?:\(\s*continued\s*\))?(.*)$",
    re.IGNORECASE,
)
ITEM_HEADING_CORE = r"ITEMS?\s+(\d+[A-Z]?(?:\.\d{1,2})?)"
RE_ITEM_HEADING = re.compile(
    rf"^\s*(?:[\|+•\t-]\s*)?{ITEM_HEADING_CORE}\b(?:\s*[:.\-]\s*|\s+)?(?:\(\s*continued\s*\))?(.*)$",
    re.IGNORECASE,
)

# The item-number grammar of exact cover headings: a decimal fused to a
# title-case title, or a plain number with an optional short decimal tail.
ITEM_NUMBER_PATTERN = r"(?:\d+\.\d{1,2}(?=[A-Z])|\d+[A-Z]?(?:\.\d{1,2})?\b)"
RE_ITEM_EXACT = re.compile(
    rf"^\s*ITEMS?\s+{ITEM_NUMBER_PATTERN}\s*(?:[.:;\-\u2013\u2014]+\s*)?"
    r"(?:(?-i:[A-Z])[A-Za-z0-9,&'()\s-]*)?[:.]?\s*"
    r"(?:\(\s*continued\s*\))?\s*$",
    re.IGNORECASE,
)
RE_ITEM_SECTION_HEADING = re.compile(
    rf"^\s*(?:[\|+•\t-]\s*)?ITEMS?\s+({ITEM_NUMBER_PATTERN})(?:\s*[:.\-]\s*|\s+)?(?:\(\s*continued\s*\))?(.*)$",
    re.IGNORECASE,
)
RE_ITEM_INLINE = re.compile(r"\bITEMS?\s+(\d+[A-Z]?(?:\.\d{1,2})?)\b", re.IGNORECASE)
RE_SECTION_REFERENCE = re.compile(
    r"\b(?:PART|ITEM)\s+(?:[IVX]+|[0-9]+[A-Z]?)\b\s*(.*)",
    re.IGNORECASE,
)

# Grouped references: two or more numbers joined by commas and conjunctions,
# the keyword optionally repeated before each later number.
_REFERENCE_CONJUNCTION = build_alternation(
    [r",\s*(?:and|&)", r"and", r"&", r","], auto_escape=False
)
RE_NOTE_GROUPED = re.compile(
    rf"\bNOTES?\s+(\d+(?:(?:\s*{_REFERENCE_CONJUNCTION}\s*(?:NOTES?\s+)?)\d+)+)\b",
    re.IGNORECASE,
)
RE_ITEM_GROUPED = re.compile(
    rf"\bITEMS?\s+(\d+[A-Z]?(?:(?:\s*{_REFERENCE_CONJUNCTION}\s*(?:ITEMS?\s+)?)\d+[A-Z]?)+)\b",
    re.IGNORECASE,
)

# Numeric and parenthesized heading forms: the numbered-section counterparts
# of the keyword headings, with the number and title captured.
RE_NUMERIC_LABEL = re.compile(
    r"^\s*(?:[\|+•\t-]\s*)?(\d{1,2}[A-Z]?)\.\s+([A-Z][A-Za-z0-9\s,&'-]+)$"
)
RE_NUMERIC_RUN_IN = re.compile(r"^\s*(?:[\|+•\t-]\s*)?(\d{1,2}[A-Z]?)\.\s+(.+)$")
RE_PAREN_LABEL = re.compile(r"^\((\d{1,2})\)\s*(.+)$")

# Caption and cue forms: the shapes other routes use to veto or admit a line.
RE_NOTE_CAPTION = re.compile(r"(?i)^\s*note\s+\d{1,3}(?:\s*[\.\):\-]\s*|\s+)[a-z]")
_HEADING_LINE_ALT = build_alternation(
    (
        r"item\s+[0-9a-z]+[.:]?",
        r"\(?[0-9]{1,2}\s*[\.\):]?",
    ),
    auto_escape=False,
    compact=True,
)
RE_ITEM_OR_NUMBERED_HEADING = re.compile(rf"(?i)^\s*(?:{_HEADING_LINE_ALT})\s+[a-z]")
RE_NOTE_HEADING_CUE = re.compile(r"notes to|^\s*note\s+\d", re.IGNORECASE)
RE_ITEM_HEADING_MARKER = re.compile(r"(?i)\bITEM\s+\d+[A-Z]?\s*[.:]\s+[A-Z]")
RE_SEE_REFERENCE = re.compile(r"(?i)\bsee\s+(?:item|row)\s+(\d+)")


def is_toc_row(line: str) -> bool:
    """Return whether ``line`` looks like a dot-leader TOC row."""
    stripped = line.strip().strip("|+")
    if not stripped:
        return False
    if RE_TOC_LEADER.search(stripped) and RE_PAGE_SUFFIX.search(stripped):
        return bool(
            RE_PART_REFERENCE.search(stripped) or RE_ITEM_REFERENCE.search(stripped)
        )
    return False


def looks_like_toc_row(line: str) -> bool:
    """Return whether ``line`` matches any TOC row form.
    Covers dot-leader rows and leader-less rows opening with an ITEM reference and carrying a page suffix, the shape an HTML table TOC produces when columns replace leaders.
    """
    stripped = line.strip().strip("|+")
    if not stripped:
        return False
    if is_toc_row(stripped):
        return True
    return bool(
        RE_TOC_ITEM_ROW.match(stripped)
        and (RE_TOC_LEADER.search(stripped) or RE_PAGE_SUFFIX.search(stripped))
    )


RE_PAGE_RANGE = re.compile(
    r"^(?:[A-Z]-)?(\d{1,3})\s*[\u2013\u2014-]\s*(?:[A-Z]-)?\d{1,3}$"
)
_TOC_TITLE_PAGE = re.compile(
    r"^(?P<title>.{4,}?)\s+(?P<page>(?:[A-Z]-)?\d{1,3}"
    r"(?:\s*[\u2013\u2014-]\s*(?:[A-Z]-)?\d{1,3})?)$"
)


def page_range_start(cell: str) -> int | None:
    """The start page of a page-range cell (``12-14``, ``F-12 - F-14``)."""
    match = RE_PAGE_RANGE.match(cell.strip())
    return int(match.group(1)) if match else None


def toc_title_parts(line: str) -> tuple[str, str] | None:
    """Split a TOC-formed title line into (title, page token).

    The padded cover-TOC form: a title of at least four characters
    closed by a bare, namespaced, or ranged page reference, with no
    dot leader required — the shape a contents line takes when it
    rides as a note title over a filing's tables.
    """
    stripped = line.strip().strip("|+")
    if not stripped or is_toc_row(stripped):
        return None
    match = _TOC_TITLE_PAGE.match(stripped)
    if match is None:
        return None
    title = match.group("title").strip(" .")
    if not any(char.isalpha() for char in title):
        return None
    return title, match.group("page")


def looks_like_toc_tabular(line: str) -> bool:
    """Return whether a line is dot-leader tabular content with a page token.
    Uses the shared patterns, so ``F-1`` and roman page tokens count.
    """
    stripped = line.strip().strip("|+")
    if not stripped:
        return False
    return bool(RE_DOT_LEADER.search(stripped) and RE_PAGE_SUFFIX.search(stripped))


__all__ = [
    "RE_ITEM_EXACT",
    "RE_ITEM_GROUPED",
    "RE_ITEM_HEADING",
    "RE_ITEM_HEADING_MARKER",
    "RE_ITEM_INLINE",
    "RE_ITEM_OR_NUMBERED_HEADING",
    "RE_ITEM_REFERENCE",
    "RE_ITEM_SECTION_HEADING",
    "RE_NOTE_CAPTION",
    "RE_NOTE_GROUPED",
    "RE_NOTE_HEADING",
    "RE_NOTE_HEADING_CUE",
    "RE_NOTE_REFERENCE",
    "RE_NUMERIC_LABEL",
    "RE_NUMERIC_RUN_IN",
    "RE_PAGE_RANGE",
    "RE_PAGE_SUFFIX",
    "RE_PAREN_LABEL",
    "RE_PART_REFERENCE",
    "RE_SECTION_REFERENCE",
    "RE_SEE_REFERENCE",
    "RE_TOC_ITEM",
    "RE_TOC_ITEM_ROW",
    "RE_TOC_LEADER",
    "is_toc_row",
    "looks_like_toc_row",
    "looks_like_toc_tabular",
    "page_range_start",
    "toc_title_parts",
]
