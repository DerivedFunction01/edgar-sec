"""Tests for financial statement section transition bridge terms and patterns."""

from __future__ import annotations

from edgar_sec.domain.taxonomy.statements.bridge import (
    FINANCIAL_BRIDGE_TERMS,
    FINANCIAL_TABLE_BRIDGE_RE,
)


def test_bridge_terms_populated() -> None:
    assert len(FINANCIAL_BRIDGE_TERMS) > 0
    assert "operating activities" in FINANCIAL_BRIDGE_TERMS
    assert "current liabilities" in FINANCIAL_BRIDGE_TERMS


def test_financial_table_bridge_re_matches() -> None:
    assert FINANCIAL_TABLE_BRIDGE_RE.match("Liabilities and stockholders' equity:")
    assert FINANCIAL_TABLE_BRIDGE_RE.match("Operating activities")
    assert FINANCIAL_TABLE_BRIDGE_RE.match("Current liabilities")


def test_financial_table_bridge_re_rejects_irrelevant() -> None:
    assert not FINANCIAL_TABLE_BRIDGE_RE.match("Overview of operations")
    assert not FINANCIAL_TABLE_BRIDGE_RE.match("General commentary")
