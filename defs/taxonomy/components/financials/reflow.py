"""Financial predicates used when reflow joins statement regions."""

from __future__ import annotations

import re

from defs.regex import build_alternation
from defs.taxonomy.components.financials.balance import (
    BALANCE_SHEET_TAIL_RE,
)
from defs.taxonomy.components.financials.cash_flow import CASH_FLOW_TAIL_RE
from defs.taxonomy.components.financials.equity import EQUITY_STATEMENT_TAIL_RE
from defs.taxonomy.components.financials.income import INCOME_STATEMENT_TAIL_RE
from defs.taxonomy.components.schedules.stock_comp import STOCK_COMP_TAIL_RE

_FINANCIAL_BRIDGE_TERMS = (
    "liabilities and stockholders' equity",
    "liabilities and stockholders' deficit",
    "liabilities and shareholders' equity",
    "liabilities and shareholders' deficit",
    "current liabilities",
    "long-term debt",
    "commitments and contingencies",
    "commitments & contingencies",
    "stockholders' equity",
    "shareholders' equity",
    "operating activities",
    "investing activities",
    "financing activities",
    "supplemental cash flow disclosures",
    "supplemental cash flow information",
)
_FINANCIAL_BRIDGE_PATTERN = build_alternation(
    _FINANCIAL_BRIDGE_TERMS,
    auto_escape=True,
    flexible_whitespace=True,
    compact=True,
)
FINANCIAL_TABLE_BRIDGE_RE = re.compile(
    rf"^\s*{_FINANCIAL_BRIDGE_PATTERN}(?=\s|:|$)", re.IGNORECASE
)


def is_financial_table_bridge_line(line: str) -> bool:
    """Return whether a line is a known financial statement section label."""

    return FINANCIAL_TABLE_BRIDGE_RE.match(line) is not None


def is_financial_table_tail_line(line: str) -> bool:
    """Return whether a line begins with a family-owned financial tail label."""

    return any(
        pattern.match(line) is not None
        for pattern in (
            BALANCE_SHEET_TAIL_RE,
            CASH_FLOW_TAIL_RE,
            EQUITY_STATEMENT_TAIL_RE,
            INCOME_STATEMENT_TAIL_RE,
            STOCK_COMP_TAIL_RE,
        )
    )


__all__ = [
    "FINANCIAL_TABLE_BRIDGE_RE",
    "is_financial_table_bridge_line",
    "is_financial_table_tail_line",
]
