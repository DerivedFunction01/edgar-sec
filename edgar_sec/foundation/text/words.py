"""The shared word tokenizer for filing prose and row labels."""

from __future__ import annotations

import re

WORD_TOKEN_RE: re.Pattern[str] = re.compile(r"[a-z][a-z']+")


def word_tokens(text: str) -> list[str]:
    """Word tokens of text, lowercased: letters and apostrophes, never digits."""
    return WORD_TOKEN_RE.findall(text.lower())


__all__ = ["WORD_TOKEN_RE", "word_tokens"]
