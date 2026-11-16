"""TOC regex patterns and compiled constants. Owns only the TOC-block shapes —
heading, PART/ITEM row with a captured ordinal, multi-item row, and weak
`INDEX`/`REFERENCE` headings that row evidence can promote.
"""

from __future__ import annotations

import re

from edgar_sec.engine.tables.toc.patterns import RE_TOC_ITEM, RE_TOC_LEADER
from edgar_sec.foundation.regex.builder import compact_alternation

RE_TOC_HEADING = re.compile(
    r"^\s*(?:[\|+]\s*)?(?:table\s+of\s+)?contents(?:\s*\([^)]*\))?(?:\s*[\|+])?\s*$",
    re.IGNORECASE,
)
RE_TOC_PART_TEXT = re.compile(r"\bp\s*a\s*r\s*t\s+(?:[ivxlcdm]+|\d+)\b", re.IGNORECASE)
RE_TOC_PART_ROW = re.compile(
    r"^\s*(?:[\|+]\s*)?PART\s+([IVXLCDM]+|\d+)\b", re.IGNORECASE
)
RE_TOC_NUMERIC_LABEL = re.compile(r"^\s*\d{1,2}[A-Z]?[.\)]\s")

WEAK_TOC_HEADINGS = ("index", "reference", "references")
_RE_WEAK_HEADING = re.compile(
    rf"^\s*(?:[\|+]\s*)?{compact_alternation(WEAK_TOC_HEADINGS)}(?:\s*[\|+])?\s*$",
    re.IGNORECASE,
)

__all__ = [
    "RE_TOC_HEADING",
    "RE_TOC_ITEM",
    "RE_TOC_NUMERIC_LABEL",
    "RE_TOC_PART_ROW",
    "RE_TOC_PART_TEXT",
    "WEAK_TOC_HEADINGS",
]
