"""Shared text normalisation for the extraction package."""

from __future__ import annotations

from edgar_sec.foundation.text.normalize import collapse_whitespace, fold_smart_quotes


def normalize_text(text: str) -> str:
    """Canonical label form: lowercased, quotes folded, whitespace collapsed."""
    folded = fold_smart_quotes(text.lower())
    return " ".join(collapse_whitespace(folded).split()).strip(" :.")


def normalize_label(text: str) -> str:
    """Validation's match-label form: like normalize_text, quotes not folded."""
    return " ".join(collapse_whitespace(text.lower()).split()).strip(" :.")


def collapse_text(text: str) -> str:
    """Whitespace collapse only: case, quotes, and edge punctuation preserved."""
    return " ".join(collapse_whitespace(text).split())
