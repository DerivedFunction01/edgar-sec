"""Income statement (Operations / Earnings) terms and structural tail patterns.

Ported from v1 defs/taxonomy/components/financials/income.py with exact empirical
filing definitions. Owns income statement section labels and tail patterns.
"""

from __future__ import annotations

import re

from edgar_sec.foundation.regex.builder import build_alternation

REVENUE_TERMS: tuple[str, ...] = (
    "total revenues",
    "total revenue",
    "total net revenues",
    "total net sales",
    "net sales",
    "revenues",
    "revenue",
    "sales and service revenues",
)

COST_OF_SALES_TERMS: tuple[str, ...] = (
    "cost of revenue",
    "cost of revenues",
    "cost of sales",
    "cost of goods sold",
    "costs of sales",
)

GROSS_PROFIT_TERMS: tuple[str, ...] = (
    "gross profit",
    "gross margin",
)

OPERATING_EXPENSES_TERMS: tuple[str, ...] = (
    "total operating expenses",
    "operating expenses",
    "research and development",
    "selling, general and administrative",
    "general and administrative",
    "sales and marketing",
)

OPERATING_INCOME_TERMS: tuple[str, ...] = (
    "operating income",
    "operating loss",
    "operating income (loss)",
    "income from operations",
    "loss from operations",
)

EPS_TERMS: tuple[str, ...] = (
    "basic earnings per share",
    "diluted earnings per share",
    "basic and diluted earnings per share",
    "earnings per share",
    "basic per share",
    "diluted per share",
    "per share - basic",
    "per share - diluted",
)

INCOME_STATEMENT_TAIL_TERMS: tuple[str, ...] = (
    "net income",
    "net loss",
    "net income (loss)",
    "basic earnings per share",
    "diluted earnings per share",
    "basic and diluted earnings per share",
)

_INCOME_STATEMENT_TAIL_PATTERN = build_alternation(
    INCOME_STATEMENT_TAIL_TERMS,
    auto_escape=True,
    flexible_whitespace=True,
    compact=True,
)

INCOME_STATEMENT_TAIL_RE = re.compile(
    rf"^\s*{_INCOME_STATEMENT_TAIL_PATTERN}(?=\s|$)", re.IGNORECASE
)

INCOME_STATEMENT_VETOES: tuple[str, ...] = ("activities",)

__all__ = [
    "COST_OF_SALES_TERMS",
    "EPS_TERMS",
    "GROSS_PROFIT_TERMS",
    "INCOME_STATEMENT_TAIL_RE",
    "INCOME_STATEMENT_TAIL_TERMS",
    "INCOME_STATEMENT_VETOES",
    "OPERATING_EXPENSES_TERMS",
    "OPERATING_INCOME_TERMS",
    "REVENUE_TERMS",
]
