"""Tests for income statement line items and tail patterns."""

from __future__ import annotations

from edgar_sec.domain.taxonomy.statements.income import (
    COST_OF_SALES_TERMS,
    EPS_TERMS,
    GROSS_PROFIT_TERMS,
    INCOME_STATEMENT_TAIL_RE,
    INCOME_STATEMENT_TAIL_TERMS,
    INCOME_STATEMENT_VETOES,
    OPERATING_EXPENSES_TERMS,
    OPERATING_INCOME_TERMS,
    REVENUE_TERMS,
)


def test_income_statement_terms_populated() -> None:
    assert len(REVENUE_TERMS) > 0
    assert len(COST_OF_SALES_TERMS) > 0
    assert len(GROSS_PROFIT_TERMS) > 0
    assert len(OPERATING_EXPENSES_TERMS) > 0
    assert len(OPERATING_INCOME_TERMS) > 0
    assert len(EPS_TERMS) > 0
    assert len(INCOME_STATEMENT_TAIL_TERMS) > 0
    assert "activities" in INCOME_STATEMENT_VETOES


def test_income_tail_regex_matches() -> None:
    assert INCOME_STATEMENT_TAIL_RE.match("Net income (loss) 10 9")
    assert INCOME_STATEMENT_TAIL_RE.match("Diluted earnings per share 1.25")
    assert INCOME_STATEMENT_TAIL_RE.match("Net loss 450")


def test_income_tail_regex_rejects_non_tail() -> None:
    assert not INCOME_STATEMENT_TAIL_RE.match("Net commentary 10 9")
    assert not INCOME_STATEMENT_TAIL_RE.match("Operating expenses 200")
