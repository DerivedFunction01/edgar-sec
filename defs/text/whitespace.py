"""Representation-neutral final text whitespace normalization."""

from __future__ import annotations

import re

_RE_MULTIPLE_BLANKS = re.compile(r"\n{3,}")
_RE_TRAILING_WHITESPACE = re.compile(r"[ \t]+$", re.MULTILINE)


def normalize_final_text_whitespace(text: str) -> str:
    """Remove line-end padding and collapse excessive blank lines."""
    text = _RE_TRAILING_WHITESPACE.sub("", text)
    return _RE_MULTIPLE_BLANKS.sub("\n\n", text)


__all__ = ["normalize_final_text_whitespace"]
