"""Contract tests for family-owned table tail vocabularies."""

from __future__ import annotations

from defs.taxonomy.components.financials.balance import BALANCE_SHEET_TAIL_RE
from defs.taxonomy.components.financials.cash_flow import CASH_FLOW_TAIL_RE
from defs.taxonomy.components.financials.equity import EQUITY_STATEMENT_TAIL_RE
from defs.taxonomy.components.financials.income import INCOME_STATEMENT_TAIL_RE
from defs.taxonomy.components.schedules.stock_comp import STOCK_COMP_TAIL_RE


def test_balance_tail_regex_is_specific() -> None:
    assert BALANCE_SHEET_TAIL_RE.match("Total assets       100  90")
    assert BALANCE_SHEET_TAIL_RE.match(
        "Total liabilities and stockholders' deficit  100  90"
    )
    assert not BALANCE_SHEET_TAIL_RE.match("Total commentary 100 90")


def test_cash_flow_tail_regex_handles_period_variants() -> None:
    assert CASH_FLOW_TAIL_RE.match("Cash and cash equivalents at end of year  10  9")
    assert CASH_FLOW_TAIL_RE.match(
        "Cash   and cash equivalents at beginning of period  10  9"
    )
    assert not CASH_FLOW_TAIL_RE.match("Net revenue 10 9")


def test_other_family_tail_regexes_do_not_match_generic_words() -> None:
    assert INCOME_STATEMENT_TAIL_RE.match("Net income (loss) 10 9")
    assert EQUITY_STATEMENT_TAIL_RE.match("Ending balance 10 9")
    assert STOCK_COMP_TAIL_RE.match("Weighted-average shares outstanding 10 9")
    assert not INCOME_STATEMENT_TAIL_RE.match("Net commentary 10 9")
