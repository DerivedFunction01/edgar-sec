"""Vocabulary and extraction regexes specific to annual reports."""

from __future__ import annotations

import re

from defs.regex import build_alternation

INCORPORATED_REFERENCE_TERMS: tuple[str, ...] = (
    "documents incorporated by reference",
    "incorporated by reference",
    "part iii of this form 10-k",
    "part iii of this report",
)

ANNUAL_REPORT_TITLES: tuple[str, ...] = (
    "annual report pursuant to section 13 or 15(d) of the securities exchange act of 1934",
    "annual report pursuant to section 13 or 15(d)",
    "annual report under section 13",
    "transition report pursuant to section 13 or 15(d)",
    "transition report pursuant to section 13",
    "for the fiscal year ended",
    "for the transition period from",
    "index to report",
)

DELINQUENT_FILERS_TERMS: tuple[str, ...] = (
    "pursuant to item 405 of regulation s-k",
    "pursuant to item 405",
    "delinquent filers",
    "disclosure of delinquent filers",
)

PUBLIC_FLOAT_PHRASES: tuple[str, ...] = (
    "state the aggregate market value of the voting and non-voting common equity held by non-affiliates",
    "the aggregate market value of the voting and non-voting common equity held by non-affiliates",
    "aggregate market value of voting and non-voting common equity held by non-affiliates",
    "aggregate market value of the voting and non-voting common equity held by non-affiliates",
    "aggregate market value of the voting and non-voting stock held by non-affiliates",
    "aggregate market value of the common stock held by non-affiliates",
    "aggregate market value of the common equity held by non-affiliates",
    "aggregate market value of voting and non-voting common stock held by non-affiliates",
    "voting and non-voting common equity held by non-affiliates",
    "voting and non-voting common equity",
    "last business day of the registrant's most recently completed second fiscal quarter",
    "most recently completed second fiscal quarter",
    "last business day",
    "aggregate market value",
    "non-affiliates",
)

SHARES_PHRASES: tuple[str, ...] = (
    "indicate the number of shares outstanding of each of the registrant's classes of common stock",
    "indicate the number of shares outstanding of each of the issuer's classes of common stock",
    "indicate the number of shares outstanding of each of the registrant's classes of common stock as of",
    "indicate the number of shares outstanding of each of the issuer's classes of common stock as of",
    "indicate the number of shares outstanding of each of the registrant's classes of common equity",
    "indicate the number of shares outstanding of each of the issuer's classes of common equity",
    "number of shares of common stock outstanding",
    "shares of common stock outstanding",
    "number of shares of common stock",
    "number of shares outstanding",
    "shares of the issuer",
    "par value outstanding",
    "shares outstanding",
)

# Compiled public float & shares patterns
PUBLIC_FLOAT_ANCHOR_RE = re.compile(
    build_alternation(
        [PUBLIC_FLOAT_PHRASES[0]], auto_escape=True, flexible_whitespace=True
    ),
    re.IGNORECASE,
)

_FLOAT_UNIT = (
    rf"(?:{build_alternation(['billion', 'million', 'thousand'], auto_escape=True)})?"
)
_FLOAT_VALUE_INNER = (
    rf"\$\s*[\d][\d,.]{{0,15}}\s*{_FLOAT_UNIT}"
    rf"|\b\d[\d,.]{{0,15}}\s*{_FLOAT_UNIT}\s*dollars\b"
)
PUBLIC_FLOAT_VALUE_RE = re.compile(rf"({_FLOAT_VALUE_INNER})", re.IGNORECASE)
PUBLIC_FLOAT_EXACT_RE = re.compile(r"(\$\s*[\d][\d,.]{3,})", re.IGNORECASE)

SHARES_ANCHOR_RE = re.compile(
    rf"(?:"
    rf"{build_alternation([SHARES_PHRASES[0]], auto_escape=True, flexible_whitespace=True)}"
    rf"|"
    rf"{build_alternation([SHARES_PHRASES[1]], auto_escape=True, flexible_whitespace=True)}"
    rf")",
    re.IGNORECASE,
)
SHARES_VALUE_RE = re.compile(
    r"\b(?:\d{1,3}(?:,\d{3})+|\d{5,12})\b\s*(?:shares\b)?", re.IGNORECASE
)

__all__ = [
    "ANNUAL_REPORT_TITLES",
    "DELINQUENT_FILERS_TERMS",
    "INCORPORATED_REFERENCE_TERMS",
    "PUBLIC_FLOAT_ANCHOR_RE",
    "PUBLIC_FLOAT_EXACT_RE",
    "PUBLIC_FLOAT_PHRASES",
    "PUBLIC_FLOAT_VALUE_RE",
    "SHARES_ANCHOR_RE",
    "SHARES_PHRASES",
    "SHARES_VALUE_RE",
]
