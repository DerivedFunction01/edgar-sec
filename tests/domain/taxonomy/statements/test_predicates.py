"""Tests for financial statement section bridge and tail line predicates."""

from __future__ import annotations

from edgar_sec.domain.taxonomy.statements.predicates import (
    is_financial_table_bridge_line,
    is_financial_table_tail_line,
)


def test_balance_sheet_tail_lines_are_recognized() -> None:
    assert is_financial_table_tail_line("Total assets") is True
    assert is_financial_table_tail_line("total liabilities") is True
    assert (
        is_financial_table_tail_line("Total liabilities and stockholders' equity")
        is True
    )
    assert (
        is_financial_table_tail_line("Total liabilities and shareholders' deficit")
        is True
    )


def test_cash_flow_tail_lines_are_recognized() -> None:
    assert (
        is_financial_table_tail_line("Cash and cash equivalents at end of period")
        is True
    )
    assert (
        is_financial_table_tail_line("Net increase in cash and cash equivalents")
        is True
    )


def test_equity_and_income_tail_lines_are_recognized() -> None:
    assert is_financial_table_tail_line("Ending balance") is True
    assert is_financial_table_tail_line("Net income") is True
    assert is_financial_table_tail_line("Net income (loss)") is True
    assert is_financial_table_tail_line("Basic earnings per share") is True


def test_stock_comp_tail_lines_are_recognized() -> None:
    assert is_financial_table_tail_line("Weighted-average shares outstanding") is True


def test_generic_lines_are_not_tail_lines() -> None:
    assert is_financial_table_tail_line("Total commentary follows") is False
    assert is_financial_table_tail_line("General and administrative expenses") is False
    assert is_financial_table_tail_line("Item 1. Business") is False


def test_financial_bridge_lines_are_recognized() -> None:
    assert (
        is_financial_table_bridge_line("Liabilities and stockholders' equity:") is True
    )
    assert is_financial_table_bridge_line("Operating activities") is True
    assert is_financial_table_bridge_line("Long-term debt") is True
    assert is_financial_table_bridge_line("Commitments and contingencies") is True
    assert is_financial_table_bridge_line("Supplemental cash flow disclosures") is True


def test_non_bridge_lines_are_rejected() -> None:
    assert is_financial_table_bridge_line("Note 1 - Organization") is False
    assert is_financial_table_bridge_line("Overview of operations") is False
