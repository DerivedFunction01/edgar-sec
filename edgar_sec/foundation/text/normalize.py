"""Canonical Unicode and whitespace normalization primitives."""

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

_RE_STRIP_ZERO_WIDTH = re.compile(f"[{''.join(STRIP_ZERO_WIDTH)}]+")
_RE_NORMALIZE_SPACE = re.compile(f"[{''.join(NORMALIZE_TO_SPACE)}]")
_RE_MULTI_BLANKS = re.compile(r"\n{3,}")
_RE_MULTI_SPACES = re.compile(r"[ \t]+")


def sanitize_unicode_whitespace(text: str) -> str:
    """Normalize Unicode whitespace: special spaces -> ASCII space, strip zero-width chars."""
    if not text:
        return ""
    text = _RE_STRIP_ZERO_WIDTH.sub("", text)
    return _RE_NORMALIZE_SPACE.sub(" ", text)


def collapse_whitespace(text: str) -> str:
    """Collapse contiguous horizontal whitespace into single spaces and strip leading/trailing."""
    if not text:
        return ""
    return _RE_MULTI_SPACES.sub(" ", text).strip()


def collapse_excessive_blank_lines(text: str) -> str:
    """Collapse sequences of three or more newlines into double newlines (paragraph separator)."""
    if not text:
        return ""
    return _RE_MULTI_BLANKS.sub("\n\n", text)


__all__ = [
    "NORMALIZE_TO_SPACE",
    "STRIP_ZERO_WIDTH",
    "collapse_excessive_blank_lines",
    "collapse_whitespace",
    "sanitize_unicode_whitespace",
]
