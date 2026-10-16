"""Compiled regexes for filing periods, amendments, and box header dates."""

from __future__ import annotations

import re

from edgar_sec.foundation.regex.builder import build_alternation

PERIOD_MATCH_RE = re.compile(
    r"Statement for(?:\s*\([^\)]*\))?\s*:?\s*([A-Za-z0-9/,\- ]+)",
    re.IGNORECASE,
)
AMEND_MATCH_RE = re.compile(r"Date of Original[^\n]*\n([^\n]+)", re.IGNORECASE)

BOX5_SPLIT_TERMS = (
    "5. if amendment",
    "5.if amendment",
    "if amendment",
    "date of original",
)
BOX5_SPLIT_ALT = build_alternation(BOX5_SPLIT_TERMS, auto_escape=True)
BOX5_SPLIT_RE = re.compile(rf"(?i)(?:{BOX5_SPLIT_ALT})")

PERIOD_PREFIX_TERMS = (
    r"4\.\s*",
    r"statement\s+for\s*(?:\([^)]*\))?\s*:?\s*",
    r"\(?month\s*/\s*(?:day\s*/\s*)?year\)?\s*:?\s*",
    r"\(?month\s*/\s*year\)?\s*:?\s*",
)
PERIOD_PREFIX_ALT = build_alternation(PERIOD_PREFIX_TERMS, auto_escape=False)
PERIOD_PREFIX_RE = re.compile(rf"(?i)^(?:{PERIOD_PREFIX_ALT})+")

AMEND_LABEL_TERMS = (
    r"5\.\s*if\s+amendment[^\n]*",
    r"5\.if\s+amendment[^\n]*",
    r"if\s+amendment[^\n]*",
    r"date\s+of\s+original[^\n]*",
    r"\(?month\s*/\s*(?:day\s*/\s*)?year\)?",
)
AMEND_LABEL_ALT = build_alternation(AMEND_LABEL_TERMS, auto_escape=False)
AMEND_LABEL_RE = re.compile(rf"(?i)^(?:{AMEND_LABEL_ALT})\s*$")

AMEND_DATE_CLEAN_RE = re.compile(
    r"^(?:5\.\s*|date\s+of\s+original\s*:?\s*)", re.IGNORECASE
)

__all__ = [
    "AMEND_DATE_CLEAN_RE",
    "AMEND_LABEL_ALT",
    "AMEND_LABEL_RE",
    "AMEND_LABEL_TERMS",
    "AMEND_MATCH_RE",
    "BOX5_SPLIT_ALT",
    "BOX5_SPLIT_RE",
    "BOX5_SPLIT_TERMS",
    "PERIOD_MATCH_RE",
    "PERIOD_PREFIX_ALT",
    "PERIOD_PREFIX_RE",
    "PERIOD_PREFIX_TERMS",
]
