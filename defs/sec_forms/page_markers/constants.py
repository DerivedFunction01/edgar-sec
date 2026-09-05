"""Regex patterns, constants, and numeral definitions for page marker detection."""

from __future__ import annotations

import re

from defs.regex import build_alternation
from defs.text.patterns import PAGE_NUMBER_CORE

from .models import PageMarkerKind

_RE_PAGE_NUMBER_OF_TOTAL = re.compile(
    r"(?im)^[ \t]*page[ \t]+(?P<page>\d+)[ \t]+of[ \t]+(?P<count>\d+)[ \t]*$"
)
_RE_NUMBER_OF_TOTAL = re.compile(
    r"(?im)^[ \t]*(?P<page>\d+)[ \t]+of[ \t]+(?P<count>\d+)[ \t]*$"
)
_RE_PAGE_NUMBER = re.compile(
    r"(?im)^[ \t]*page[ \t]+(?P<page>\d+)[ \t]*$", re.IGNORECASE
)
_RE_DASHED_NUMBER = re.compile(r"(?im)^[ \t]*-[ \t]*(?P<page>\d+)[ \t]*-[ \t]*$")
_RE_LETTER_NUMBER = re.compile(
    r"(?im)^\s*(?:page\s+)?(?P<prefix>[A-Z])\s*[-–—]\s*(?P<page>\d+)\s*$"
)
_RE_SGML_LINE = re.compile(
    r"(?im)^[ \t]*</?PAGE\b[^>]*>[ \t]*(?P<page>\d+)?[ \t]*"
    r"(?:</?PAGE\b[^>]*>)?[ \t]*$"
)
_RE_SGML_INLINE = re.compile(r"(?i)</?PAGE\b[^>]*>")
_RE_BOUNDARY = re.compile(r"(?im)^[ \t]*(?:\(PAGE\)|\[PAGE\])[ \t]*$")
_WRAPPERS = build_alternation(["-", "–", "—", ".", "·", "•", "▪"], auto_escape=True)
_RE_DASH_LABEL = re.compile(
    rf"^(?=.*(?:{_WRAPPERS}))(?:{_WRAPPERS}|\s)+"
    rf"(?P<value>\d{{1,4}}|[ivxlcdm]{{1,8}})"
    rf"(?:{_WRAPPERS}|\s)+$",
    re.IGNORECASE,
)
_RE_PIPE_LABEL = re.compile(
    r"^\|\s*(?P<value>\d{1,4}|[ivxlcdm]{1,8})\s*\|$", re.IGNORECASE
)
_RE_PAREN_LABEL = re.compile(
    r"^\(\s*(?P<value>\d{1,4}|[ivxlcdm]{1,8})\s*\)$", re.IGNORECASE
)
_RE_SIMPLE_WRAPPED_LABEL = re.compile(
    r"^(?:[|]\s*\d{1,4}\s*[|]|\(\s*\d{1,4}\s*\)|\d{1,4}\.)$"
)
_RE_DOTTED_LABEL = re.compile(r"^(?P<value>\d{1,4})\.$")
_RE_BARE_ARABIC = re.compile(r"^(?P<value>\d{1,4})$")
_RE_BARE_ROMAN = re.compile(r"^(?P<value>[ivxlcdm]{1,8})$", re.IGNORECASE)
_RE_LEADING_NUMBER = re.compile(r"^(?P<value>\d{1,4})\s{1,}\S.*$")
_RE_TRAILING_NUMBER = re.compile(r"^\S.*?\s{2,}(?P<value>\d{1,4})$")
_RE_INLINE_PAGE = re.compile(
    r"^(?P<prefix>.{0,80}?\bpage\s+)(?P<value>\d{1,4})\b(?P<suffix>.{0,80})$",
    re.IGNORECASE,
)
_STRUCTURAL_WORDS = build_alternation(
    ["part", "item", "exhibit", "note"], auto_escape=True
)
_PAGE_MARKER_PATTERNS = (
    (PageMarkerKind.PAGE_NUMBER_OF_TOTAL, _RE_PAGE_NUMBER_OF_TOTAL),
    (PageMarkerKind.NUMBER_OF_TOTAL, _RE_NUMBER_OF_TOTAL),
    (PageMarkerKind.PAGE_NUMBER, _RE_PAGE_NUMBER),
    (PageMarkerKind.DASHED_NUMBER, _RE_DASHED_NUMBER),
    (PageMarkerKind.LETTER_NUMBER, _RE_LETTER_NUMBER),
    (PageMarkerKind.SGML, _RE_SGML_LINE),
    (PageMarkerKind.SGML, _RE_SGML_INLINE),
)
RE_PAGE_SUFFIX = re.compile(
    rf"(?:\b[A-Z])?[\.\-\s]?{PAGE_NUMBER_CORE}(?:\s*[\|+])?\s*$",
    re.IGNORECASE,
)

_NUMERALS = (
    ("m", 1000),
    ("cm", 900),
    ("d", 500),
    ("cd", 400),
    ("c", 100),
    ("xc", 90),
    ("l", 50),
    ("xl", 40),
    ("x", 10),
    ("ix", 9),
    ("v", 5),
    ("iv", 4),
    ("i", 1),
)

_PAGE_WORDS = build_alternation(
    [
        "page",
        "page-no",
        "page_no",
        "pageno",
        "page-number",
        "page_number",
        "folio",
        "pgbrk",
        "pagebreak",
        "footer",
    ],
    auto_escape=True,
)
_TOC_WORDS = build_alternation(
    ["toc", "contents", "table-of-contents", "table_of_contents", "index"],
    auto_escape=True,
)
_VALUE_RE = re.compile(
    r"^(?:page\s+)?(?P<value>\d{1,4}|[ivxlcdm]{1,8})$|"
    r"^(?:[-–—|·•▪()]\s*)+(?P<wrapped>\d{1,4}|[ivxlcdm]{1,8})"
    r"(?:\s*[-–—|·•▪()])+$",
    re.IGNORECASE,
)
_NUMERIC_RE = re.compile(r"^(?P<value>\d{1,4})$")
_HIDDEN_STYLE_VALUES = build_alternation(
    [r"display\s*:\s*none", r"visibility\s*:\s*hidden", "hidden"]
)
_HIDDEN_STYLE_RE = re.compile(rf"(?:{_HIDDEN_STYLE_VALUES})", re.IGNORECASE)
_PAGE_BREAK_PROPERTIES = build_alternation(
    ["page-break-before", "page-break-after", "break-before", "break-after"],
    auto_escape=True,
)
_PAGE_BREAK_VALUES = build_alternation(
    ["always", "left", "right", "page"], auto_escape=True
)
_PAGE_BREAK_RE = re.compile(
    rf"(?:{_PAGE_BREAK_PROPERTIES})\s*:\s*(?:{_PAGE_BREAK_VALUES})\b",
    re.IGNORECASE,
)
_PAGE_BREAK_AVOID_RE = re.compile(
    rf"(?:{_PAGE_BREAK_PROPERTIES})\s*:\s*avoid\b",
    re.IGNORECASE,
)
_RE_HIDDEN_TEMPLATE = re.compile(r"(?:^|[\s_-])(?:hidden|template)(?:$|[\s_-])")
_RE_PAGE_SEMANTIC = re.compile(rf"(?:^|[\s_-])(?:{_PAGE_WORDS})(?:$|[\s_-])")
_RE_TOC_SEMANTIC = re.compile(rf"(?:^|[\s_-])(?:{_TOC_WORDS})(?:$|[\s_-])")
_RE_STRUCTURAL_MATCH = re.compile(rf"(?i)^(?:{_STRUCTURAL_WORDS})\b")
_RE_APPENDIX_ROMAN = re.compile(
    r"^(?P<prefix>[A-Za-z])-(?P<value>[ivxlcdm]{1,8})$",
    re.IGNORECASE,
)

__all__ = [
    "RE_PAGE_SUFFIX",
    "_HIDDEN_STYLE_RE",
    "_HIDDEN_STYLE_VALUES",
    "_NUMERALS",
    "_NUMERIC_RE",
    "_PAGE_BREAK_AVOID_RE",
    "_PAGE_BREAK_PROPERTIES",
    "_PAGE_BREAK_RE",
    "_PAGE_BREAK_VALUES",
    "_PAGE_MARKER_PATTERNS",
    "_PAGE_WORDS",
    "_RE_APPENDIX_ROMAN",
    "_RE_BARE_ARABIC",
    "_RE_BARE_ROMAN",
    "_RE_BOUNDARY",
    "_RE_DASHED_NUMBER",
    "_RE_DASH_LABEL",
    "_RE_DOTTED_LABEL",
    "_RE_HIDDEN_TEMPLATE",
    "_RE_INLINE_PAGE",
    "_RE_LEADING_NUMBER",
    "_RE_LETTER_NUMBER",
    "_RE_NUMBER_OF_TOTAL",
    "_RE_PAGE_NUMBER",
    "_RE_PAGE_NUMBER_OF_TOTAL",
    "_RE_PAGE_SEMANTIC",
    "_RE_PAREN_LABEL",
    "_RE_PIPE_LABEL",
    "_RE_SGML_INLINE",
    "_RE_SGML_LINE",
    "_RE_SIMPLE_WRAPPED_LABEL",
    "_RE_STRUCTURAL_MATCH",
    "_RE_TOC_SEMANTIC",
    "_RE_TRAILING_NUMBER",
    "_STRUCTURAL_WORDS",
    "_TOC_WORDS",
    "_VALUE_RE",
    "_WRAPPERS",
]
