"""Centralized numeric and currency parsing for SEC forms."""

from __future__ import annotations

import re

from edgar_sec.engine.tables.numeric_cells import CURRENCY_TOKEN_RE

_NUMERIC_TOKEN_RE = re.compile(
    rf"^\s*\(?\s*(?:{CURRENCY_TOKEN_RE.pattern})?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:{CURRENCY_TOKEN_RE.pattern})?\s*\)?\b"
)
_PUNCT_STRIP_RE = re.compile(rf"[,\s]|(?:{CURRENCY_TOKEN_RE.pattern})")
_PREFIXES = ("up to", "approx.", "approx")
_NULL_TOKENS = frozenset({"-", "--", "none", "n/a", "nil", "null"})


def clean_numeric(text: str | None) -> float | int | None:
    """Extract and parse numeric amounts from formatted cell strings."""
    if not text:
        return None
    cleaned = text.strip()
    lower = cleaned.lower()
    if lower in _NULL_TOKENS:
        return None
    for prefix in _PREFIXES:
        if lower.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
            lower = cleaned.lower()
            break

    match = _NUMERIC_TOKEN_RE.search(cleaned)
    if not match:
        return None

    raw_val = _PUNCT_STRIP_RE.sub("", match.group(1))
    is_negative = cleaned.startswith("(") and cleaned.endswith(")")
    try:
        if "." in raw_val:
            num = float(raw_val)
        else:
            num = int(raw_val)
        return -num if is_negative else num
    except ValueError:
        return None


__all__ = ["clean_numeric"]
