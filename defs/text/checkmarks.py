"""Shared checkbox token vocabulary and raw token patterns."""

from __future__ import annotations

import re

from defs.regex import build_alternation

CANONICAL_CHECKED = "[X]"
CANONICAL_UNCHECKED = "[ ]"

BRACKET_PAIRS = (("[", "]"), ("(", ")"), ("/", "/"), ("|", "|"))
CHECKED_INNER = (
    "x",
    "X",
    " x ",
    " X ",
    "✓",
    "✔",
    "☑",
    "☒",
    "■",
    "▪",
    "●",
    "✘",
    "þ",
    "ý",
)
UNCHECKED_INNER = (" ", "  ", "_", " _ ", "&nbsp;", " &nbsp; ")

CHECKED_HTML_ENTITIES = (
    "&#9746;",
    "&#9745;",
    "&#254;",
    "&#253;",
    "&#084;",
    "&#84;",
    "&#120;",
)
UNCHECKED_HTML_ENTITIES = (
    "&#9744;",
    "&#111;",
    "&#083;",
    "&#83;",
    "&#168;",
)

CHECKED_SYMBOLS = (
    "☒",
    "☑",
    "✓",
    "✔",
    "þ",
    "ý",
    "■",
    "▪",
    "●",
    "✘",
)
UNCHECKED_SYMBOLS = ("☐", "□", "¨")

RAW_CHECKED_TOKENS = (
    *CHECKED_SYMBOLS,
    *CHECKED_HTML_ENTITIES,
    *(
        f"{left}{inner}{right}"
        for left, right in BRACKET_PAIRS
        for inner in CHECKED_INNER
    ),
)
RAW_UNCHECKED_TOKENS = (
    *UNCHECKED_SYMBOLS,
    *UNCHECKED_HTML_ENTITIES,
    *(
        f"{left}{inner}{right}"
        for left, right in BRACKET_PAIRS
        for inner in UNCHECKED_INNER
    ),
)

RE_RAW_CHECKED = re.compile(
    build_alternation(RAW_CHECKED_TOKENS, auto_escape=True), re.IGNORECASE
)
RE_RAW_UNCHECKED = re.compile(
    build_alternation(RAW_UNCHECKED_TOKENS, auto_escape=True), re.IGNORECASE
)

CHECKED_TOKENS = frozenset(RAW_CHECKED_TOKENS)
UNCHECKED_TOKENS = frozenset(RAW_UNCHECKED_TOKENS)

__all__ = [
    "BRACKET_PAIRS",
    "CANONICAL_CHECKED",
    "CANONICAL_UNCHECKED",
    "CHECKED_HTML_ENTITIES",
    "CHECKED_INNER",
    "CHECKED_SYMBOLS",
    "CHECKED_TOKENS",
    "RAW_CHECKED_TOKENS",
    "RAW_UNCHECKED_TOKENS",
    "RE_RAW_CHECKED",
    "RE_RAW_UNCHECKED",
    "UNCHECKED_HTML_ENTITIES",
    "UNCHECKED_INNER",
    "UNCHECKED_SYMBOLS",
    "UNCHECKED_TOKENS",
]
