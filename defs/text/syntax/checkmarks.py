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


BRACKET_PAIRS = (
    ("[", "]"),
    ("(", ")"),
    ("{", "}"),
    ("/", "/"),
    ("|", "|"),
    ("\\", "\\"),
)
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

# Filled geometric glyphs remain available for explicit filer-grid geometry.
# Asterisks and plus signs are excluded because they are commonly footnotes,
# operators, or prose punctuation rather than checkbox glyphs.
CONTEXT_CHECKED_SYMBOLS = ("●", "■", "▪", "•")
CONTEXT_UNCHECKED_SYMBOLS = ("o", "O")

# The cleaner is the only stage allowed to interpret these encoded glyphs.
# Keys are normalized font family names; values are source glyph -> state.
FONT_GLYPH_MAPPINGS = {
    "wingdings": {
        "r": "unchecked",
        "R": "unchecked",
        "o": "unchecked",
        "O": "unchecked",
        "x": "checked",
        "X": "checked",
        "þ": "checked",
        "ý": "checked",
        "¨": "unchecked",
    },
    "wingdings 2": {
        "r": "unchecked",
        "R": "unchecked",
        "o": "unchecked",
        "O": "unchecked",
        "x": "checked",
        "X": "checked",
        "þ": "checked",
        "ý": "checked",
        "¨": "unchecked",
        "£": "checked",
        "S": "checked",
    },
    "wingdings2": {
        "r": "unchecked",
        "R": "unchecked",
        "o": "unchecked",
        "O": "unchecked",
        "x": "checked",
        "X": "checked",
        "þ": "checked",
        "ý": "checked",
        "¨": "unchecked",
        "£": "checked",
        "S": "checked",
    },
    "webdings": {
        "r": "unchecked",
        "R": "unchecked",
        "o": "unchecked",
        "O": "unchecked",
        "x": "checked",
        "X": "checked",
        "þ": "checked",
        "ý": "checked",
    },
    "symbol": {"þ": "checked", "ý": "checked"},
}

FONT_BULLET_GLYPH_MAPPINGS = {
    "wingdings": {"n": "•", "u": "○"},
    "wingdings 2": {"n": "•", "u": "○"},
    "wingdings2": {"n": "•", "u": "○"},
    "webdings": {"n": "•", "u": "○"},
    "symbol": {},
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


def font_bullet_glyph_state(font_family: str, glyph: str) -> str | None:
    """Return the mapped canonical bullet character for one symbolic font glyph."""
    families = [
        part.strip().strip("\"'").lower()
        for part in font_family.split(",")
        if part.strip()
    ]
    for family in families:
        mapping = FONT_BULLET_GLYPH_MAPPINGS.get(family)
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

CHECKED_TOKENS = frozenset(RAW_CHECKED_TOKENS)
UNCHECKED_TOKENS = frozenset(RAW_UNCHECKED_TOKENS)

# Bare glyphs are candidates only; their semantic state may depend on the
# source font or cover/grid context.
BARE_MARK_TOKENS = ("x", "X", "o", "O", "þ", "ý", "r", "R")

# Candidate extraction uses the complete mark vocabulary, including marks
# whose meaning requires cover context. Semantic association remains phase-owned.
CHECKMARK_MARK_TOKENS = (
    *RAW_CHECKED_TOKENS,
    *RAW_UNCHECKED_TOKENS,
    *CONTEXT_CHECKED_SYMBOLS,
    *BARE_MARK_TOKENS,
)
# Bracketed tokens match without trailing word-boundary constraints
# so that `[X]No` and `company[X]` are recognized as checkmark tokens.
# Bare glyphs require word boundaries and must not appear inside
# bracket delimiters (preventing bare `X` inside `[X]` from
# double-expanding to `[[X]]`).
_BRACKETED_MARK_TOKENS = tuple(
    f"{left}{inner}{right}"
    for left, right in BRACKET_PAIRS
    for inner in CHECKED_INNER + UNCHECKED_INNER
)
_BARE_MARK_TOKENS = BARE_MARK_TOKENS
# Non-bracketed, non-bare tokens: symbols, HTML entities, context symbols
_OTHER_MARK_TOKENS = tuple(
    t
    for t in CHECKMARK_MARK_TOKENS
    if t not in _BRACKETED_MARK_TOKENS and t not in _BARE_MARK_TOKENS
)

MARK_OPEN = r"[\[\(\{]"
MARK_CLOSE = r"[\]\)\}]"
CHECKED_SYMBOL = r"[xX✓✔☑☒✘]"
SPACED_BLANK = r"\s{1,8}"
UNDERSCORE_RUN = r"_{1,8}"


def _wrapped_mark_pattern(symbol: str) -> str:
    """Build the shared bracket, slash, pipe, and backslash wrapper structure."""
    return (
        rf"(?:{MARK_OPEN}\s*{symbol}\s*{MARK_CLOSE}|"
        rf"/\s*{symbol}\s*/|\|\s*{symbol}\s*\||\\\s*{symbol}\s*\\)"
    )


_VARIABLE_CHECKED_SAFE_PATTERN = _wrapped_mark_pattern(CHECKED_SYMBOL)
_VARIABLE_CHECKED_PATTERN = (
    rf"(?:{_VARIABLE_CHECKED_SAFE_PATTERN}|"
    rf"{UNDERSCORE_RUN}\s*{CHECKED_SYMBOL}\s*{UNDERSCORE_RUN}|"
    rf"{UNDERSCORE_RUN}\s*{CHECKED_SYMBOL}|"
    rf"{CHECKED_SYMBOL}\s*{UNDERSCORE_RUN})"
)
_VARIABLE_UNCHECKED_SAFE_PATTERN = (
    rf"(?:{MARK_OPEN}{SPACED_BLANK}{MARK_CLOSE}|"
    rf"{MARK_OPEN}\s*[_-]{{1,8}}\s*{MARK_CLOSE}|"
    rf"/\s{{1,8}}/|\|\s{{1,8}}\||\\\s{{1,8}}\\)"
)
_VARIABLE_UNCHECKED_PATTERN = (
    rf"(?:{_VARIABLE_UNCHECKED_SAFE_PATTERN}|"
    rf"_\s{{1,8}}_|{UNDERSCORE_RUN})"
)

CHECKMARK_MARK_RE = re.compile(
    "(?<![\\w])(?:"
    + build_alternation(_OTHER_MARK_TOKENS, auto_escape=True)
    + ")(?![\\w])"
    "|(?<![\\w[({])(?:"
    + build_alternation(_BARE_MARK_TOKENS, auto_escape=True)
    + ")(?![\\w])"
    + f"|{_VARIABLE_CHECKED_PATTERN}"
    + f"|{_VARIABLE_UNCHECKED_PATTERN}"
    "|" + build_alternation(_BRACKETED_MARK_TOKENS, auto_escape=True)
)

RE_VARIABLE_CHECKED = re.compile(rf"^{_VARIABLE_CHECKED_PATTERN}$")
RE_VARIABLE_UNCHECKED = re.compile(rf"^{_VARIABLE_UNCHECKED_PATTERN}$")

# Keep variable-width wrappers in the state recognizers as well as candidate
# extraction; otherwise a token can be found but still be treated as unknown.
RE_RAW_CHECKED = re.compile(
    rf"(?<![A-Za-z0-9_])(?:{build_alternation(RAW_CHECKED_TOKENS, auto_escape=True)}|"
    rf"{_VARIABLE_CHECKED_SAFE_PATTERN})(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
RE_RAW_UNCHECKED = re.compile(
    rf"(?<![A-Za-z0-9_])(?:{build_alternation(RAW_UNCHECKED_TOKENS, auto_escape=True)}|"
    rf"{_VARIABLE_UNCHECKED_SAFE_PATTERN})(?![A-Za-z0-9_])",
    re.IGNORECASE,
)


def is_unchecked_mark_token(value: str) -> bool:
    """Return whether a token is a variable-width blank mark candidate."""
    token = value.strip()
    return bool(RE_VARIABLE_UNCHECKED.fullmatch(token)) or (
        len(token) >= 2 and set(token) <= {"_", "-"}
    )


def is_fill_in_mark_token(value: str) -> bool:
    """Return whether a token is an underscore/dash cover fill-in run."""
    token = value.strip()
    return bool(token) and set(token) <= {"_", "-"}


__all__ = [
    "BARE_MARK_TOKENS",
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
    "FONT_BULLET_GLYPH_MAPPINGS",
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
    "font_bullet_glyph_state",
    "font_glyph_state",
    "is_fill_in_mark_token",
    "is_unchecked_mark_token",
]
