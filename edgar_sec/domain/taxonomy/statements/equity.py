"""Statement of Stockholders' Equity and Comprehensive Income terms and tail patterns.

Ported from v1 defs/taxonomy/components/financials/equity.py with exact empirical
filing definitions. Owns equity statement section labels and tail patterns.
"""

from __future__ import annotations

import re

from edgar_sec.foundation.regex.builder import build_alternation

EQUITY_PRIMARY_TERMS: tuple[str, ...] = (
    "balance at",
    "additional paid-in capital",
    "accumulated other comprehensive",
    "retained earnings",
    "common stock",
    "treasury stock",
    "shares outstanding",
    "comprehensive income",
)

EQUITY_SUPPORTING_TERMS: tuple[str, ...] = (
    "stock-based compensation",
    "dividends declared",
    "net income",
    "repurchase of common stock",
)

EQUITY_STATEMENT_TAIL_TERMS: tuple[str, ...] = (
    "balance at beginning of period",
    "balance at end of period",
    "ending balance",
    "beginning balance",
    "total stockholders' equity",
    "total shareholders' equity",
    "total equity",
)

_EQUITY_STATEMENT_TAIL_PATTERN = build_alternation(
    EQUITY_STATEMENT_TAIL_TERMS,
    auto_escape=True,
    flexible_whitespace=True,
    compact=True,
)

EQUITY_STATEMENT_TAIL_RE = re.compile(
    rf"^\s*{_EQUITY_STATEMENT_TAIL_PATTERN}(?=\s|$)", re.IGNORECASE
)

EQUITY_VETOES: tuple[str, ...] = ("activities",)

__all__ = [
    "EQUITY_PRIMARY_TERMS",
    "EQUITY_STATEMENT_TAIL_RE",
    "EQUITY_STATEMENT_TAIL_TERMS",
    "EQUITY_SUPPORTING_TERMS",
    "EQUITY_VETOES",
]
