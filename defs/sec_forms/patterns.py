"""Reusable SEC form pattern data consumed by extraction algorithms."""

from __future__ import annotations

import re

from defs.regex import build_alternation, compact_alternation
from defs.sec_forms.cover.vocabulary import PUBLIC_FLOAT_PHRASES, SHARES_PHRASES

FILER_CATEGORY_PATTERNS = (
    ("Large accelerated filer", r"large\s+accelerated\s+filer"),
    ("Non-accelerated filer", r"non[\s\-]accelerated\s+filer"),
    ("Accelerated filer", r"(?<!large\s)accelerated\s+filer"),
    ("Smaller reporting company", r"smaller\s+reporting\s+company"),
    ("Emerging growth company", r"emerging\s+growth\s+company"),
)

CHECKBOX_KEYWORDS = (
    "accelerated filer",
    "smaller reporting company",
    "emerging growth company",
    "shell company",
    "well-known seasoned issuer",
    "annual report",
    "transition report",
    "voluntary filer",
)
CHECKBOX_GRID_RE = re.compile(
    rf"\b(?:{compact_alternation(CHECKBOX_KEYWORDS)})\b",
    re.IGNORECASE,
)

PUBLIC_FLOAT_ANCHOR_RE = re.compile(
    re.escape(PUBLIC_FLOAT_PHRASES[0]).replace(r"\ ", r"\s+"), re.IGNORECASE
)
_MAGNITUDE = build_alternation(["trillion", "billion", "million"])
_FLOAT_VALUE_INNER = build_alternation(["zero", rf"\$?\s*[\d][\d,.]*\s*{_MAGNITUDE}s?"])
PUBLIC_FLOAT_VALUE_RE = re.compile(rf"({_FLOAT_VALUE_INNER})", re.IGNORECASE)
PUBLIC_FLOAT_EXACT_RE = re.compile(r"(\$\s*[\d][\d,.]{3,})", re.IGNORECASE)
_SHARES_ANCHOR_INNER = build_alternation(
    [
        re.escape(SHARES_PHRASES[0]).replace(r"\ ", r"\s+"),
        r"shares\s+of\s+[\w$.,\s]{0,40}outstanding",
        r"there\s+were\s+[\d,.]+\s+shares",
        r"issued\s+and\s+outstanding",
        re.escape(SHARES_PHRASES[1]).replace(r"\ ", r"\s+"),
    ]
)
SHARES_ANCHOR_RE = re.compile(rf"(?:{_SHARES_ANCHOR_INNER})", re.IGNORECASE)
SHARES_VALUE_RE = re.compile(r"(\d[\d,]*)\s+shares?", re.IGNORECASE)

CURRENCY_SPACING_RE = re.compile(r"\$\s+(\d)")
PUNCT_SPACING_RE = re.compile(r"\s+([,.;:!?)])")

IXBRL_FACT_RE = re.compile(r"ix:nonFraction", re.IGNORECASE)

__all__ = [
    "CHECKBOX_GRID_RE",
    "CHECKBOX_KEYWORDS",
    "CURRENCY_SPACING_RE",
    "FILER_CATEGORY_PATTERNS",
    "IXBRL_FACT_RE",
    "PUBLIC_FLOAT_ANCHOR_RE",
    "PUBLIC_FLOAT_EXACT_RE",
    "PUBLIC_FLOAT_VALUE_RE",
    "PUNCT_SPACING_RE",
    "SHARES_ANCHOR_RE",
    "SHARES_VALUE_RE",
]
