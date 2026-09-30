"""Balance sheet (Financial Position) terms and structural tail patterns.

Ported from v1 defs/taxonomy/components/financials/balance.py with exact empirical
filing definitions. Owns balance sheet section labels and tail patterns.
"""

from __future__ import annotations

import re

from edgar_sec.foundation.regex.builder import build_alternation

ASSETS_TERMS: tuple[str, ...] = (
    "total assets",
    "total current assets",
    "current assets",
    "assets",
)

LIABILITIES_TERMS: tuple[str, ...] = (
    "total liabilities",
    "total current liabilities",
    "current liabilities",
    "liabilities",
    "long-term debt",
    "long-term liabilities",
    "noncurrent liabilities",
    "commitments and contingencies",
    "commitments & contingencies",
    "redeemable preferred stock",
)

EQUITY_TERMS: tuple[str, ...] = (
    "total stockholders' equity",
    "total shareholders' equity",
    "total stockholders equity",
    "total shareholders equity",
    "total equity",
    "stockholders' equity",
    "shareholders' equity",
    "stockholders equity",
    "shareholders equity",
    "members' equity",
    "partners' equity",
    "unitholders' equity",
    "retained earnings",
    "common stock",
    "additional paid-in capital",
)

CASH_TERMS: tuple[str, ...] = (
    "cash and cash equivalents",
    "cash and equivalents",
    "marketable securities",
    "short-term investments",
)

BALANCE_SHEET_TAIL_TERMS: tuple[str, ...] = (
    "total assets",
    "total liabilities",
    "total liabilities and stockholders' equity",
    "total liabilities and stockholders' deficit",
    "total liabilities and shareholders' equity",
    "total liabilities and shareholders' deficit",
    "total liabilities and members' equity",
    "total liabilities and partners' equity",
    "total liabilities and unitholders' equity",
)

_BALANCE_SHEET_TAIL_PATTERN = build_alternation(
    BALANCE_SHEET_TAIL_TERMS,
    auto_escape=True,
    flexible_whitespace=True,
    compact=True,
)

BALANCE_SHEET_TAIL_RE = re.compile(
    rf"^\s*{_BALANCE_SHEET_TAIL_PATTERN}(?=\s|$)", re.IGNORECASE
)

BALANCE_SHEET_VETOES: tuple[str, ...] = ("activities",)

__all__ = [
    "ASSETS_TERMS",
    "BALANCE_SHEET_TAIL_RE",
    "BALANCE_SHEET_TAIL_TERMS",
    "BALANCE_SHEET_VETOES",
    "CASH_TERMS",
    "EQUITY_TERMS",
    "LIABILITIES_TERMS",
]
