"""Compiled regular expressions for SEC table detection and parsing."""

from __future__ import annotations

import re

from defs.regex import build_alternation, build_regex

from .tokens import (
    BULLET_MARKERS,
    CURRENCY_TOKEN_RE,
    FINANCIAL_PLACEHOLDERS,
    NUMERIC_CELL_RE,
)

# --- BASIC REGEX PATTERNS ---
CAPTION_RE = re.compile(
    r"<caption[^>]*>(.*?)(?:</caption\s*>|(?=\n\s*\n|\n\s*<S>|\n\s*[-=]{3,}|\Z))",
    re.IGNORECASE | re.DOTALL,
)
TABLE_TAG_RE = re.compile(r"<TABLE.*?>", re.DOTALL | re.IGNORECASE)
S_MARKER_RE = re.compile(r"<S>")
C_MARKER_RE = re.compile(r"<C>")
HTML_TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")
NUMERIC_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
NUMERIC_WITH_SYMBOLS = re.compile(rf"(?:{CURRENCY_TOKEN_RE.pattern}|[%()\-,])")
PERCENT_HEADER_RE = re.compile(
    rf"\b(?:%|{build_alternation(['percentage', 'percent'])})\b", re.IGNORECASE
)

# Canonical patterns used while classifying and healing HTML financial tables.
PAREN_SPACES_RE = re.compile(r"\(\s+([^\)]+?)\s+\)")
FOOTNOTE_RE = re.compile(r"^\(?[a-zA-Z0-9\*\†\‡\§\d]{1,3}\)?$")
YEAR_TOKEN_RE = re.compile(r"^\b(202[0-9]|201[0-9]|200[0-9]|199[0-9])\b$")
YEAR_IN_HEADER_RE = re.compile(r"\b\d{4}\b")
BULLET_MARKER_RE = re.compile(
    rf"^(?:{build_alternation(sorted(BULLET_MARKERS), auto_escape=True)}|\(?\d{{1,2}}[\.\)]?|\(?[a-zA-Z][\.\)]?)$"
)
HIDDEN_ELEMENT_STYLE_RE = re.compile(
    r"(?:display:\s*none|visibility:\s*hidden)", re.IGNORECASE
)

# Safe patterns for years in tables
YEAR_RE = build_regex([r"(?:\d{1,2}/)+(\d{2,4})", r"(19[8-9]\d|20\d{2})"])

# Header detection keywords
LAST_HEADER_PATTERN = build_regex(
    [
        "notional",
        "fair",
        "location",
        "carrying",
        "level",
        "maturity",
        "rate",
        "yield",
        "weighted",
        "amount",
        "value",
        "balance",
        "principal",
        "gain",
        "loss",
        "income",
        "asset",
        "liability",
        "status",
        "date",
    ]
)

# Multipliers constructed via build_alternation
_MULT_PREFIX = build_alternation([r"in", r"dollars\s+in"])
_UNIT_TERMS = build_alternation(
    [
        r"thousands?",
        r"millions?",
        r"billions?",
        r"trillions?",
    ]
)

THOUSAND_RE = re.compile(
    rf"(?:{_MULT_PREFIX})\s+thousands|\(000(?:['\s]s)?\)", re.IGNORECASE
)
MILLION_RE = re.compile(
    rf"(?:{_MULT_PREFIX})\s+millions|\(000(?:,000)?(?:['\s]s)?\)", re.IGNORECASE
)
BILLION_RE = re.compile(rf"(?:{_MULT_PREFIX})\s+billions", re.IGNORECASE)
UNIT_RE = re.compile(rf"\s*{_UNIT_TERMS}", re.IGNORECASE)

from .currencies import PREFIX_SYMBOLS

# Symbol cleaning
_PREFIX_SYM_ALT = build_alternation(
    PREFIX_SYMBOLS, auto_escape=True, sort_longest_first=True
)
CURRENCY_SPACE_RE = re.compile(rf"({_PREFIX_SYM_ALT})\s+")
OPEN_PAREN_SPACE_RE = re.compile(r"\(\s+")
CLOSE_PAREN_SPACE_RE = re.compile(r"\s+\)")
NUMERIC_PERCENT_SPACE_RE = re.compile(
    r"(?<![A-Za-z])(\(?[+-]?\d[\d,]*(?:\.\d+)?\)?)[ \t]+%"
)
COMMA_SPACE_RE = re.compile(r",\s+")
SPACE_COMMA_RE = re.compile(r"\s+,")

# Paragraph masquerading detection
TABLE_OF_CONTENTS_RE = re.compile(r"\.{3,}")
PARAGRAPH_THRESHOLD = 250

__all__ = [
    "BILLION_RE",
    "BULLET_MARKER_RE",
    "CAPTION_RE",
    "CLOSE_PAREN_SPACE_RE",
    "COMMA_SPACE_RE",
    "CURRENCY_SPACE_RE",
    "C_MARKER_RE",
    "FINANCIAL_PLACEHOLDERS",
    "FOOTNOTE_RE",
    "HIDDEN_ELEMENT_STYLE_RE",
    "HTML_TAG_RE",
    "LAST_HEADER_PATTERN",
    "MILLION_RE",
    "NUMERIC_CELL_RE",
    "NUMERIC_PERCENT_SPACE_RE",
    "NUMERIC_RE",
    "NUMERIC_WITH_SYMBOLS",
    "OPEN_PAREN_SPACE_RE",
    "PARAGRAPH_THRESHOLD",
    "PAREN_SPACES_RE",
    "PERCENT_HEADER_RE",
    "SPACE_COMMA_RE",
    "S_MARKER_RE",
    "TABLE_OF_CONTENTS_RE",
    "TABLE_TAG_RE",
    "THOUSAND_RE",
    "UNIT_RE",
    "WHITESPACE_RE",
    "YEAR_RE",
    "YEAR_IN_HEADER_RE",
    "YEAR_TOKEN_RE",
]
