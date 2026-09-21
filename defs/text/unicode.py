"""Canonical Unicode whitespace normalization constants and utilities."""

from __future__ import annotations

import re

NORMALIZE_TO_SPACE = frozenset(
    {
        "\u00a0",  # NO-BREAK SPACE
        "\u2007",  # FIGURE SPACE
        "\u202f",  # NARROW NO-BREAK SPACE
        "\u2009",  # THIN SPACE
    }
)

STRIP_ZERO_WIDTH = frozenset(
    {
        "\u200b",  # ZERO WIDTH SPACE
        "\u200c",  # ZERO WIDTH NON-JOINER
        "\u200d",  # ZERO WIDTH JOINER
        "\u200e",  # LEFT-TO-RIGHT MARK
        "\u200f",  # RIGHT-TO-LEFT MARK
        "\u061c",  # ARABIC LETTER MARK
        "\u202a",  # LEFT-TO-RIGHT EMBEDDING
        "\u202b",  # RIGHT-TO-LEFT EMBEDDING
        "\u202c",  # POP DIRECTIONAL FORMATTING
        "\u202d",  # LEFT-TO-RIGHT OVERRIDE
        "\u202e",  # RIGHT-TO-LEFT OVERRIDE
        "\u2066",  # LEFT-TO-RIGHT ISOLATE
        "\u2067",  # RIGHT-TO-LEFT ISOLATE
        "\u2068",  # FIRST STRONG ISOLATE
        "\u2069",  # POP DIRECTIONAL ISOLATE
        "\ufeff",  # ZERO WIDTH NO-BREAK SPACE (BOM)
    }
)


_UNICODE_TRANS = str.maketrans(
    {ch: " " for ch in NORMALIZE_TO_SPACE} | {ch: None for ch in STRIP_ZERO_WIDTH}
)

# Regex-based equivalents of _UNICODE_TRANS: str.translate performs a Python
# dict lookup per character, while C-level character-class substitution skips
# non-matching spans, which is over an order of magnitude faster on
# multi-megabyte filings. The replacement order matches the translate
# semantics: zero-width removal first, then special-space normalization.
_RE_STRIP_ZERO_WIDTH = re.compile(f"[{''.join(STRIP_ZERO_WIDTH)}]+")
_RE_NORMALIZE_SPACE = re.compile(f"[{''.join(NORMALIZE_TO_SPACE)}]")


def sanitize_unicode_whitespace(text: str) -> str:
    """Normalize Unicode whitespace: special spaces -> ASCII space, strip zero-width chars."""
    if not text:
        return ""
    text = _RE_STRIP_ZERO_WIDTH.sub("", text)
    return _RE_NORMALIZE_SPACE.sub(" ", text)


__all__ = [
    "NORMALIZE_TO_SPACE",
    "STRIP_ZERO_WIDTH",
    "sanitize_unicode_whitespace",
]
