"""Rollforward grid features: the shared derivation's priced reads."""

from __future__ import annotations

import edgar_sec.engine.tables.extraction.evidence.rollforward_grid_evidence as _rge
from edgar_sec.engine.tables.extraction.evidence.rollforward_grid_evidence import (
    RollforwardGridText,
    grid_features,
)
from edgar_sec.foundation.text.dates import STRICT_YEAR_TOKEN_PATTERN


def _features(table_text: str):
    return grid_features(RollforwardGridText(table_text))


def test_year_reads_are_the_strict_century_form():
    assert _rge._YEAR_RE.pattern == rf"\b(?:{STRICT_YEAR_TOKEN_PATTERN})\b"
    features = _features("Item | 2019 | 2100 | 3000")
    assert features.span == 1


def test_span_counts_distinct_years_over_all_lines():
    features = _features("A | 2019 | 2020\nB | 2020 | 2021")
    assert features.span == 3
    assert features.rows == 2


def test_bookend_from_anchor_pair():
    text = (
        "Balance at January 1, 2019 | 100\n"
        "Charges | 5\n"
        "Balance at December 31, 2019 | 105"
    )
    assert _features(text).bookend_f2


def test_bookend_from_beginning_and_end_anchors():
    text = "Balance, beginning of period | 100\nBalance, end of period | 100"
    assert _features(text).bookend_f2


def test_no_bookend_on_a_plain_year_matrix():
    text = "Activity | 2019 | 2020 | 2021\nLease termination | 10 | 20 | 30"
    assert not _features(text).bookend_f2


def test_balances_unchanged_needs_two_equal_walks():
    text = "Balance, beginning of period | 100\nBalance, end of period | 100"
    assert _features(text).balances_unchanged
    changed = "Balance, beginning of period | 100\nBalance, end of period | 90"
    assert not _features(changed).balances_unchanged
    single = "Balance, end of period | 100"
    assert not _features(single).balances_unchanged


def test_movement_nonzero_counts_movement_word_lines():
    text = (
        "Balance, beginning of period | 100\n"
        "Charges | 0\n"
        "Payments | 5\n"
        "Balance, end of period | 105"
    )
    assert _features(text).movement_nonzero == 2


def test_pct_density_over_numeric_cells():
    features = _features("Alpha | 50% | 10\nBeta | 30% | 20")
    assert features.pct_density == 0.5
    split = _features("Alpha | 50 | % | 10 | 20")
    assert split.pct_density == 1 / 3


def test_prose_cells_need_six_tokens():
    features = _features("Note | the quick brown fox jumps over | 5")
    assert features.prose_cells == 1
    short = _features("Note | too short a cell | 5")
    assert short.prose_cells == 0


def test_inventory_core_needs_two_components_and_a_total():
    text = "Raw materials | 10\nWork in process | 20\nTotal inventories | 30"
    features = _features(text)
    assert features.inventory_components == 2
    assert features.inventory_core
    one = _features("Raw materials | 10\nTotal inventories | 30")
    assert not one.inventory_core
    no_total = _features("Raw materials | 10\nFinished goods | 20")
    assert not no_total.inventory_core


def test_packet_and_rows_surfaces_agree():
    rows = (("Accrual", "2019", "2020", "2021"), ("Charges", "1", "2", "3"))
    via_rows = grid_features(RollforwardGridText.from_rows(rows))
    via_packet = grid_features(
        RollforwardGridText.from_packet(
            {"table_text": "Accrual | 2019 | 2020 | 2021\nCharges | 1 | 2 | 3"}
        )
    )
    assert via_rows == via_packet


def test_empty_grid_reads_zero():
    features = _features("")
    assert features.rows == 0
    assert features.span == 0
    assert features.pct_density == 0.0
