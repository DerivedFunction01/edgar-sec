"""Financial magnitude and unit-scale parsing with anti-coincidence guardrails."""

from __future__ import annotations

from functools import lru_cache
import re

from edgar_sec.engine.tables.numeric_cells import CURRENCY_TOKEN_RE
from edgar_sec.foundation.regex.builder import build_alternation

_NUMERIC_TOKEN_RE = re.compile(
    rf"^\s*\(?\s*(?:{CURRENCY_TOKEN_RE.pattern})?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:{CURRENCY_TOKEN_RE.pattern})?\s*\)?\b"
)
_PUNCT_STRIP_RE = re.compile(rf"[,\s]|(?:{CURRENCY_TOKEN_RE.pattern})")
_PREFIXES = ("up to", "approx.", "approx")
_NULL_TOKENS = frozenset({"-", "--", "none", "n/a", "nil", "null"})

_SCALE_MULTIPLIERS: dict[str, int] = {
    "k": 1_000,
    "thousand": 1_000,
    "thousands": 1_000,
    "m": 1_000_000,
    "mm": 1_000_000,
    "million": 1_000_000,
    "millions": 1_000_000,
    "b": 1_000_000_000,
    "billion": 1_000_000_000,
    "billions": 1_000_000_000,
}

_SCALE_ALT = build_alternation(tuple(_SCALE_MULTIPLIERS.keys()))

_SCALED_NUMERIC_RE = re.compile(
    rf"^\s*([\$€£]?)\s*([\d,]+(?:\.\d+)?)\s*({_SCALE_ALT})?\s*$",
    re.IGNORECASE,
)

_HYPHENATED_ALPHA_RE = re.compile(r"[a-z0-9]-[a-z0-9]", re.IGNORECASE)
_SUB_BOX_LABEL_RE = re.compile(
    r"\(?[123]?\s*\([a-z]\)|^([123][a-z]|[a-z]\))\b", re.IGNORECASE
)
_DISALLOWED_CONTEXT_TERMS = (
    "rule",
    "form",
    "suite",
    "apt",
    "schedule",
    "cusip",
    "box",
)


def parse_scaled_number(token: str) -> int | float | None:
    """Parse financial numeric value with unit scale multipliers and guardrails."""
    clean = token.strip()
    if not clean:
        return None
    if _HYPHENATED_ALPHA_RE.search(clean) or _SUB_BOX_LABEL_RE.search(clean):
        return None
    lower = clean.lower()
    if any(k in lower for k in _DISALLOWED_CONTEXT_TERMS):
        return None

    match = _SCALED_NUMERIC_RE.match(clean)
    if not match:
        return None

    currency_sym, num_str, suffix = match.groups()
    normalized_num = num_str.replace(",", "")
    try:
        val = float(normalized_num)
    except ValueError:
        return None

    if suffix:
        s_lower = suffix.lower()
        if len(s_lower) == 1 and not currency_sym and "." not in normalized_num:
            return None
        mult = _SCALE_MULTIPLIERS.get(s_lower)
        if mult:
            val = val * mult

    if val.is_integer():
        return int(val)
    return val


@lru_cache(maxsize=2048)
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


def format_scaled_number_string(token: str) -> str | None:
    """Parse and format numeric token to canonical integer or decimal string."""
    val = parse_scaled_number(token)
    if val is None:
        return None
    if isinstance(val, int) or val.is_integer():
        return str(int(val))
    return f"{val:.2f}"


__all__ = [
    "clean_numeric",
    "format_scaled_number_string",
    "parse_scaled_number",
]
