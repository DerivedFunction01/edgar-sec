"""Financial statement boundary and section label predicates.

Provides domain predicates consumed by engine table policies without coupling the
engine to specific keyword dictionaries.
"""

from __future__ import annotations

from edgar_sec.domain.taxonomy.schedules.compensation.stock_comp import (
    STOCK_COMP_TAIL_RE,
)
from edgar_sec.domain.taxonomy.statements.balance import BALANCE_SHEET_TAIL_RE
from edgar_sec.domain.taxonomy.statements.bridge import FINANCIAL_TABLE_BRIDGE_RE
from edgar_sec.domain.taxonomy.statements.cash_flow import CASH_FLOW_TAIL_RE
from edgar_sec.domain.taxonomy.statements.equity import EQUITY_STATEMENT_TAIL_RE
from edgar_sec.domain.taxonomy.statements.income import INCOME_STATEMENT_TAIL_RE

_TAIL_PATTERNS = (
    BALANCE_SHEET_TAIL_RE,
    CASH_FLOW_TAIL_RE,
    EQUITY_STATEMENT_TAIL_RE,
    INCOME_STATEMENT_TAIL_RE,
    STOCK_COMP_TAIL_RE,
)


def is_financial_table_bridge_line(line: str) -> bool:
    """Return whether a line is a known financial statement section label."""
    return FINANCIAL_TABLE_BRIDGE_RE.match(line) is not None


def is_financial_table_tail_line(line: str) -> bool:
    """Return whether a line begins with a family-owned financial tail label."""
    return any(pattern.match(line) is not None for pattern in _TAIL_PATTERNS)


__all__ = [
    "is_financial_table_bridge_line",
    "is_financial_table_tail_line",
]
