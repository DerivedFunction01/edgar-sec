"""Tests for balance sheet taxonomy terms and structural tail patterns."""

from __future__ import annotations

from edgar_sec.domain.taxonomy.statements.balance import (
    ASSETS_TERMS,
    BALANCE_SHEET_TAIL_RE,
    BALANCE_SHEET_TAIL_TERMS,
    BALANCE_SHEET_VETOES,
    CASH_TERMS,
    EQUITY_TERMS,
    LIABILITIES_TERMS,
)


def test_balance_sheet_terms_populated() -> None:
    assert len(ASSETS_TERMS) > 0
    assert len(LIABILITIES_TERMS) > 0
    assert len(EQUITY_TERMS) > 0
    assert len(CASH_TERMS) > 0
    assert len(BALANCE_SHEET_TAIL_TERMS) > 0
    assert "activities" in BALANCE_SHEET_VETOES


def test_balance_tail_regex_matches_expected() -> None:
    assert BALANCE_SHEET_TAIL_RE.match("Total assets       100  90")
    assert BALANCE_SHEET_TAIL_RE.match(
        "Total liabilities and stockholders' deficit  100  90"
    )
    assert BALANCE_SHEET_TAIL_RE.match("Total liabilities and shareholders' equity")


def test_balance_tail_regex_rejects_non_tail() -> None:
    assert not BALANCE_SHEET_TAIL_RE.match("Total commentary 100 90")
    assert not BALANCE_SHEET_TAIL_RE.match("Cash flows from operating activities")
