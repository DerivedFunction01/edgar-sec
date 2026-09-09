"""Shared checkbox vocabulary, boundaries, and font-qualified mappings."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from defs.regex import build_alternation

CANONICAL_CHECKED = "[X]"
CANONICAL_UNCHECKED = "[ ]"


@dataclass(frozen=True, slots=True)
class CheckmarkDecision:
    """One source-mark state decision made by a normalization pass."""

    source_token: str
    canonical_token: str
    state: str
    scope: str
    confidence: float
    reason: str
    source_region: str = ""
    span: tuple[int, int] | None = None


class CheckmarkScope(StrEnum):
    """Policy controlling which source marks may be interpreted."""

    GLOBAL_SAFE = "global_safe"
    COVER_CONTEXT = "cover_context"
    ALL = "all"


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
    "✘",
)
UNCHECKED_INNER = (" ", "  ", "_", " _ ", "&nbsp;", " &nbsp; ")

CHECKED_HTML_ENTITIES = (
    "&#9746;",
    "&#9745;",
)
UNCHECKED_HTML_ENTITIES = ("&#9744;",)

CHECKED_SYMBOLS = (
    "☒",
    "☑",
    "✓",
    "✔",
    "✘",
)
UNCHECKED_SYMBOLS = ("☐", "□", "¨")

# These marks are meaningful only when a cover/binary/grid decision supplies
# the missing semantic context.  They are intentionally not part of the safe
# regexes below.
CONTEXT_CHECKED_SYMBOLS = ("●", "■", "▪", "•", "*", "+", "-")
CONTEXT_UNCHECKED_SYMBOLS = ("o", "O")

# The cleaner is the only stage allowed to interpret these encoded glyphs.
# Keys are normalized font family names; values are source glyph -> state.
FONT_GLYPH_MAPPINGS = {
    "wingdings": {
        "r": "unchecked",
        "R": "unchecked",
        "þ": "checked",
        "ý": "checked",
        "¨": "unchecked",
    },
    "webdings": {"r": "unchecked", "R": "unchecked", "þ": "checked", "ý": "checked"},
    "symbol": {"r": "unchecked", "R": "unchecked", "þ": "checked", "ý": "checked"},
}


def font_glyph_state(font_family: str, glyph: str) -> str | None:
    """Return the mapped state for one explicitly named symbolic font glyph."""
    families = [
        part.strip().strip("\"'").lower()
        for part in font_family.split(",")
        if part.strip()
    ]
    for family in families:
        mapping = FONT_GLYPH_MAPPINGS.get(family)
        if mapping is not None and glyph in mapping:
            return mapping[glyph]
    return None


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
    rf"(?<![A-Za-z0-9_])(?:{build_alternation(RAW_CHECKED_TOKENS, auto_escape=True)})(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
RE_RAW_UNCHECKED = re.compile(
    rf"(?<![A-Za-z0-9_])(?:{build_alternation(RAW_UNCHECKED_TOKENS, auto_escape=True)})(?![A-Za-z0-9_])",
    re.IGNORECASE,
)

CHECKED_TOKENS = frozenset(RAW_CHECKED_TOKENS)
UNCHECKED_TOKENS = frozenset(RAW_UNCHECKED_TOKENS)

# Candidate extraction uses the complete mark vocabulary, including marks
# whose meaning requires cover context. Semantic association remains phase-owned.
CHECKMARK_MARK_TOKENS = (
    *RAW_CHECKED_TOKENS,
    *RAW_UNCHECKED_TOKENS,
    *CONTEXT_CHECKED_SYMBOLS,
    *CONTEXT_UNCHECKED_SYMBOLS,
    "x",
    "X",
    "o",
    "O",
    "þ",
    "ý",
    "r",
    "R",
)
CHECKMARK_MARK_RE = re.compile(
    rf"(?<!\w)(?:{build_alternation(CHECKMARK_MARK_TOKENS, auto_escape=True)})(?!\w)"
)

__all__ = [
    "BRACKET_PAIRS",
    "CANONICAL_CHECKED",
    "CANONICAL_UNCHECKED",
    "CHECKED_HTML_ENTITIES",
    "CHECKED_INNER",
    "CHECKED_SYMBOLS",
    "CHECKED_TOKENS",
    "CHECKMARK_MARK_RE",
    "CHECKMARK_MARK_TOKENS",
    "CONTEXT_CHECKED_SYMBOLS",
    "CONTEXT_UNCHECKED_SYMBOLS",
    "FONT_GLYPH_MAPPINGS",
    "RAW_CHECKED_TOKENS",
    "RAW_UNCHECKED_TOKENS",
    "RE_RAW_CHECKED",
    "RE_RAW_UNCHECKED",
    "UNCHECKED_HTML_ENTITIES",
    "UNCHECKED_INNER",
    "UNCHECKED_SYMBOLS",
    "UNCHECKED_TOKENS",
    "CheckmarkDecision",
    "CheckmarkScope",
    "font_glyph_state",
]
