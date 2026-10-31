"""Compiled regular expressions for SEC table detection and parsing.
Span and style patterns guard `<TABLE>` bytes; column-rule and units-label patterns recognise
statement furniture; intro cues find the sentence that introduces a grid.
"""

from __future__ import annotations

import re

from edgar_sec.foundation.regex.builder import build_alternation

RE_TABLE_BLOCK = re.compile(r"<TABLE>.*?</TABLE>", re.DOTALL)
FOOTNOTE_RE = re.compile(r"^\(?[a-zA-Z0-9\*\†\‡\§\d]{1,3}\)?$")
HIDDEN_ELEMENT_STYLE_RE = re.compile(
    r"(?:display:\s*none|visibility:\s*hidden)", re.IGNORECASE
)

# Short column-underline dash rule: multiple short groups like "---   ---".
COLUMN_DASH_RULE_RE = re.compile(r"^\s*[-=]{1,25}(?:\s+[-=]{1,25}){1,}\s*$")

_UNIT_TERMS = build_alternation(
    [
        r"thousands?",
        r"millions?",
        r"billions?",
        r"trillions?",
        r"shares?",
        r"dollars?",
        r"percent(?:age)?",
    ]
)

# Scale qualifier for a whole statement: ``(dollars in millions)``, ``(in thousands)``.
UNITS_LABEL_RE = re.compile(
    rf"\(\s*(?:(?:dollars|amounts?)\s+)?in\s+(?:{_UNIT_TERMS})[^)]*\)",
    re.IGNORECASE,
)

_TABLE_INTRO_NOUNS = build_alternation(
    (
        "table",
        "tables",
        "schedule",
        "schedules",
        "information",
        "data",
        "amounts",
        "analysis",
        "summary",
        "breakdown",
        "reconciliation",
    ),
    auto_escape=True,
    compact=True,
)
_TABLE_INTRO_LAYOUT_NOUNS = build_alternation(
    ("table", "tables", "schedule", "schedules"), auto_escape=True, compact=True
)
_TABLE_INTRO_TABLE_VERBS = build_alternation(
    ("below", "above", "presents", "present", "shows", "show", "sets forth"),
    auto_escape=True,
    compact=True,
)
_TABLE_INTRO_FOLLOWING = build_alternation(
    ("below", "in the following"), auto_escape=True, compact=True
)
_TABLE_INTRO_DISPLAY_VERBS = build_alternation(
    ("presented", "shown", "summarized"), auto_escape=True, compact=True
)
_TABLE_INTRO_RELATION = build_alternation(("as", "are"), auto_escape=True, compact=True)
_TABLE_INTRO_COLLECTION_VERBS = build_alternation(
    ("consists", "includes"), auto_escape=True, compact=True
)
_TABLE_INTRO_PATTERNS = (
    rf"the\s+following\s+(?:{_TABLE_INTRO_NOUNS})",
    rf"the\s+(?:{_TABLE_INTRO_LAYOUT_NOUNS})\s+(?:{_TABLE_INTRO_TABLE_VERBS})",
    rf"{_TABLE_INTRO_RELATION}\s+follows",
    rf"set\s+forth\s+(?:{_TABLE_INTRO_FOLLOWING})",
    rf"(?:{_TABLE_INTRO_DISPLAY_VERBS})\s+(?:{_TABLE_INTRO_FOLLOWING})",
    rf"(?:{_TABLE_INTRO_COLLECTION_VERBS})\s+of\s+the\s+following",
)
_RE_TABLE_INTRO_CUE = re.compile(
    rf"\b(?:{build_alternation(_TABLE_INTRO_PATTERNS, auto_escape=False, compact=False)})\b",
    re.IGNORECASE,
)

__all__ = [
    "COLUMN_DASH_RULE_RE",
    "FOOTNOTE_RE",
    "HIDDEN_ELEMENT_STYLE_RE",
    "RE_TABLE_BLOCK",
    "_RE_TABLE_INTRO_CUE",
    "UNITS_LABEL_RE",
]
