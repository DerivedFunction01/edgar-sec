"""Compiled regular expressions for SEC table detection and parsing."""

from __future__ import annotations

import re

# Basic regex patterns for table parsing
CAPTION_RE = re.compile(
    r"<caption[^>]*>(.*?)(?:</caption\s*>|(?=\n\s*\n|\n\s*<S>|\n\s*[-=]{3,}|\Z))",
    re.IGNORECASE | re.DOTALL,
)
TABLE_TAG_RE = re.compile(r"<TABLE.*?>", re.DOTALL | re.IGNORECASE)
RE_TABLE_BLOCK = re.compile(r"<TABLE>.*?</TABLE>", re.DOTALL)
S_MARKER_RE = re.compile(r"<S>")
C_MARKER_RE = re.compile(r"<C>")
HTML_TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")
NUMERIC_RE = re.compile(r"^-?\d+(?:\.\d+)?$")

PAREN_SPACES_RE = re.compile(r"\(\s*([^\)]+?)\s*\)")
FOOTNOTE_RE = re.compile(r"^\(?[a-zA-Z0-9\*\†\‡\§\d]{1,3}\)?$")
HIDDEN_ELEMENT_STYLE_RE = re.compile(
    r"(?:display:\s*none|visibility:\s*hidden)", re.IGNORECASE
)

__all__ = [
    "CAPTION_RE",
    "C_MARKER_RE",
    "FOOTNOTE_RE",
    "HIDDEN_ELEMENT_STYLE_RE",
    "HTML_TAG_RE",
    "NUMERIC_RE",
    "PAREN_SPACES_RE",
    "RE_TABLE_BLOCK",
    "S_MARKER_RE",
    "TABLE_TAG_RE",
    "WHITESPACE_RE",
]
