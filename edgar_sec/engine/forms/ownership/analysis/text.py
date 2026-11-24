"""Text masking and n-gram helpers for ownership review analysis."""

from __future__ import annotations

import re

from edgar_sec.foundation.text.date_patterns import MONTH_WORD_RE, NUMERIC_DATE_RE
from edgar_sec.foundation.text.patterns import RE_WHITESPACE

_CIK_MASK_RE = re.compile(r"\bCIK\s*[:#]?\s*\d{1,10}\b", re.IGNORECASE)
_DIGIT_RUN_RE = re.compile(r"\d+")
_WORD_NGRAM_RE = re.compile(r"[A-Za-z0-9#_]+")


def mask_normalized_pattern(text: str) -> str:
    """Mask text into structural placeholders for digits, months, and dates."""
    masked = _CIK_MASK_RE.sub("CIK_###", text)
    masked = NUMERIC_DATE_RE.sub("DATE_PATTERN", masked)
    masked = MONTH_WORD_RE.sub("MONTH", masked)
    masked = _DIGIT_RUN_RE.sub("###", masked)
    return RE_WHITESPACE.sub(" ", masked).strip()


def extract_word_ngrams(text: str, n: int = 2) -> list[str]:
    """Extract lowercased word n-grams from text."""
    words = [w.lower() for w in _WORD_NGRAM_RE.findall(text)]
    if n == 1:
        return words
    if len(words) < n:
        return []
    return [" ".join(words[i : i + n]) for i in range(len(words) - n + 1)]
