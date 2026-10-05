"""Tests for cash flow line items, activities trio, and tail patterns."""

from __future__ import annotations

from edgar_sec.domain.taxonomy.statements.cash_flow import (
    CASH_FLOW_ACTIVITIES_TRIO,
    CASH_FLOW_TAIL_RE,
    CASH_FLOW_TAIL_TERMS,
    CASH_FLOW_VETOES,
    FINANCING_ACTIVITIES_TERMS,
    INVESTING_ACTIVITIES_TERMS,
    OPERATING_ACTIVITIES_TERMS,
)


def test_cash_flow_terms_populated() -> None:
    assert len(OPERATING_ACTIVITIES_TERMS) > 0
    assert len(INVESTING_ACTIVITIES_TERMS) > 0
    assert len(FINANCING_ACTIVITIES_TERMS) > 0
    assert len(CASH_FLOW_ACTIVITIES_TRIO) > 0
    assert len(CASH_FLOW_TAIL_TERMS) > 0
    assert "balance sheet" in CASH_FLOW_VETOES


def test_cash_flow_tail_regex_matches_period_variants() -> None:
    assert CASH_FLOW_TAIL_RE.match("Cash and cash equivalents at end of year  10  9")
    assert CASH_FLOW_TAIL_RE.match(
        "Cash   and cash equivalents at beginning of period  10  9"
    )
    assert CASH_FLOW_TAIL_RE.match("Net increase in cash and cash equivalents")


def test_cash_flow_tail_regex_rejects_non_tail() -> None:
    assert not CASH_FLOW_TAIL_RE.match("Net revenue 10 9")
    assert not CASH_FLOW_TAIL_RE.match("Total assets 100")
