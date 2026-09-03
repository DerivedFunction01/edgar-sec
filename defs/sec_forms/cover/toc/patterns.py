"""TOC regex patterns and compiled constants."""

from __future__ import annotations

import re

from defs.regex import build_alternation, compact_alternation
from defs.text.patterns import RE_DOT_LEADER

RE_TOC_HEADING = re.compile(
    r"^\s*(?:[\|+]\s*)?(?:table\s+of\s+)?contents(?:\s*\([^)]*\))?(?:\s*[\|+])?\s*$",
    re.IGNORECASE,
)
_ITEM_CONJUNCTION = build_alternation(["and", "&", "-"], auto_escape=True)
RE_TOC_ITEM = re.compile(
    rf"^\s*(?:[\|+]\s*)?ITEMS?\s+\d+[A-Z]?(?:[\s,]+(?:{_ITEM_CONJUNCTION})?[\s,]*\d+[A-Z]?)*[\.\s]",
    re.IGNORECASE,
)
RE_TOC_PART_TEXT = re.compile(r"\bp\s*a\s*r\s*t\s+(?:[ivxlcdm]+|\d+)\b", re.IGNORECASE)

WEAK_TOC_HEADINGS = ("index", "reference", "references")
_RE_WEAK_HEADING = re.compile(
    rf"^\s*(?:[\|+]\s*)?{compact_alternation(WEAK_TOC_HEADINGS)}(?:\s*[\|+])?\s*$",
    re.IGNORECASE,
)

RE_TOC_LEADER = re.compile(rf"\s{RE_DOT_LEADER.pattern}\s")

_RE_TAGGED_TABLE = re.compile(r"<TABLE\b", re.IGNORECASE)
_RE_TAGGED_TABLE_END = re.compile(r"</TABLE\s*>", re.IGNORECASE)

_RE_NON_ALPHANUM = re.compile(r"[^a-z0-9]+")
_RE_MULTI_SPACE = re.compile(r"\s+")


__all__ = [
    "RE_TOC_HEADING",
    "RE_TOC_ITEM",
    "RE_TOC_LEADER",
    "RE_TOC_PART_TEXT",
    "WEAK_TOC_HEADINGS",
    "_RE_MULTI_SPACE",
    "_RE_NON_ALPHANUM",
    "_RE_TAGGED_TABLE",
    "_RE_TAGGED_TABLE_END",
    "_RE_WEAK_HEADING",
]
