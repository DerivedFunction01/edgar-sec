"""Tests for statement of stockholders' equity terms and tail patterns."""

from __future__ import annotations

from edgar_sec.domain.taxonomy.statements.equity import (
    EQUITY_PRIMARY_TERMS,
    EQUITY_STATEMENT_TAIL_RE,
    EQUITY_STATEMENT_TAIL_TERMS,
    EQUITY_SUPPORTING_TERMS,
    EQUITY_VETOES,
)


def test_equity_terms_populated() -> None:
    assert len(EQUITY_PRIMARY_TERMS) > 0
    assert len(EQUITY_SUPPORTING_TERMS) > 0
    assert len(EQUITY_STATEMENT_TAIL_TERMS) > 0
    assert "activities" in EQUITY_VETOES


def test_equity_tail_regex_matches() -> None:
    assert EQUITY_STATEMENT_TAIL_RE.match("Ending balance 10 9")
    assert EQUITY_STATEMENT_TAIL_RE.match("Balance at beginning of period")
    assert EQUITY_STATEMENT_TAIL_RE.match("Total stockholders' equity 500")


def test_equity_tail_regex_rejects_non_tail() -> None:
    assert not EQUITY_STATEMENT_TAIL_RE.match("Net income 100")
    assert not EQUITY_STATEMENT_TAIL_RE.match("Total commentary 10 9")
