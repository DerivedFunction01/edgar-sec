from __future__ import annotations

from edgar_sec.domain.taxonomy.schedules.compensation.stock_comp import (
    STOCK_COMP_PRIMARY_TERMS,
    STOCK_COMP_SUPPORTING_TERMS,
    STOCK_COMP_TAIL_RE,
    STOCK_COMP_TAIL_TERMS,
    STOCK_COMP_VETOES,
)


def test_stock_comp_terms_populated() -> None:
    assert len(STOCK_COMP_PRIMARY_TERMS) > 0
    assert len(STOCK_COMP_SUPPORTING_TERMS) > 0
    assert len(STOCK_COMP_TAIL_TERMS) > 0
    assert "activities" in STOCK_COMP_VETOES


def test_stock_comp_tail_regex_matches() -> None:
    assert STOCK_COMP_TAIL_RE.match("Weighted-average shares outstanding 10 9")
    assert STOCK_COMP_TAIL_RE.match("Ending balance")
    assert STOCK_COMP_TAIL_RE.match("Beginning balance")


def test_stock_comp_tail_regex_rejects_non_tail() -> None:
    assert not STOCK_COMP_TAIL_RE.match("Stock options granted 500")
    assert not STOCK_COMP_TAIL_RE.match("Operating activities")
