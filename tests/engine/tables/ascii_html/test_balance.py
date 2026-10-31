"""Header segment sizing and the sibling span width rebalancing pass."""

from __future__ import annotations

import pytest

from edgar_sec.engine.tables.ascii_html.balance import (
    balance_span_widths,
    balanced_wrap_width,
    header_minimum_width,
    preferred_header_width,
)
from edgar_sec.engine.tables.ascii_html.model import RenderBudget


def test_the_minimum_header_width_is_the_longest_unbreakable_segment() -> None:
    assert header_minimum_width("Estimated Future Payout") == 9
    assert header_minimum_width("taxable-equivalent") == 10
    assert header_minimum_width("") == 1


def test_a_short_header_is_preferred_whole() -> None:
    assert preferred_header_width("Amount") == 6
    assert preferred_header_width("  Total  ") == 5


def test_a_longer_header_is_preferred_at_a_width_that_keeps_it_to_two_lines() -> None:
    width = preferred_header_width("Estimated Future Payout Schedule")
    from edgar_sec.engine.tables.ascii_html.cell import wrap_cell_text

    assert len(wrap_cell_text("Estimated Future Payout Schedule", width)) <= 2


def test_balanced_wrapping_returns_the_whole_text_when_it_is_already_short() -> None:
    assert balanced_wrap_width("Amount", max_cap=52) == 6


def test_balanced_wrapping_never_exceeds_the_cap() -> None:
    text = "Location of Gain or (Loss) Reclassified from Accumulated Other Comprehensive Income Into Income"
    assert balanced_wrap_width(text, max_cap=52) <= 52


def test_a_repeated_header_band_may_not_widen_a_sibling_date_column() -> None:
    widths = [22, 12, 0, 0, 0, 0, 0, 0, 0, 0]
    spans = [(row, [column], "Header") for row, column in enumerate(range(2, 10))]
    balance_span_widths(
        widths,
        spans,
        set(),
        [22, 7, 1, 1, 1, 1, 1, 1, 1, 1],
        [False] * 10,
        RenderBudget(),
    )
    assert widths[1] >= 7


def test_balancing_never_increases_the_table_width() -> None:
    widths = [10, 10, 10, 10]
    budget = RenderBudget()
    spans = [(0, [0, 1], "Header One"), (0, [2, 3], "Header Two")]
    balance_span_widths(widths, spans, set(), [4, 4, 4, 4], [False] * 4, budget)
    visible = sum(width > 0 for width in widths)
    assert (
        sum(widths) + budget.column_spacing * max(0, visible - 1)
        <= budget.max_table_width
    )


def test_sibling_spans_in_the_same_row_reach_a_comparable_block_width() -> None:
    widths = [4, 4, 4, 4]
    budget = RenderBudget()
    spans = [(0, [0, 1], "Short"), (0, [2, 3], "Long Header Here")]
    balance_span_widths(widths, spans, set(), [1, 1, 1, 1], [False] * 4, budget)
    assert abs(sum(widths[:2]) - sum(widths[2:])) <= 2


def test_a_single_span_in_a_tier_is_left_alone() -> None:
    widths = [6, 6, 6]
    before = list(widths)
    balance_span_widths(
        widths, [(0, [0, 1], "Header")], set(), [1, 1, 1], [False] * 3, RenderBudget()
    )
    assert sum(widths) == sum(before)


def test_a_prefix_position_is_never_donated_from() -> None:
    widths = [8, 8, 8]
    balance_span_widths(
        widths,
        [(0, [2], "Wide Header")],
        {0},
        [1, 1, 1],
        [False] * 3,
        RenderBudget(),
    )
    assert widths[0] == 8


def test_a_blank_span_text_is_never_balanced() -> None:
    widths = [4, 4, 4]
    before = list(widths)
    balance_span_widths(
        widths, [(0, [0, 1], "   ")], set(), [1, 1, 1], [False] * 3, RenderBudget()
    )
    assert sum(widths) == sum(before)


def test_balancing_an_empty_constraint_list_is_a_no_op() -> None:
    widths = [1, 2, 3]
    balance_span_widths(widths, [], set(), [1, 1, 1], [False] * 3, RenderBudget())
    assert widths == [1, 2, 3]


def test_a_zero_width_span_origin_is_funded_from_a_donor_outside_the_header() -> None:
    widths = [0, 8, 8]
    balance_span_widths(
        widths,
        [(0, [0], "Wide Header")],
        set(),
        [1, 1, 1],
        [False] * 3,
        RenderBudget(),
    )
    assert widths[0] > 0
    assert sum(widths) <= 8 + 8 + 12


def test_a_span_origin_that_already_has_width_is_not_re_seeded() -> None:
    seeded = [0, 8, 8]
    already = [4, 8, 8]
    constraints = [(0, [0], "Wide Header")]
    for widths in (seeded, already):
        balance_span_widths(
            widths, constraints, set(), [1, 1, 1], [False] * 3, RenderBudget()
        )
    assert seeded[0] == already[0]
    assert all(width > 0 for width in seeded)


@pytest.mark.parametrize("cap", [16, 24, 32, 48])
def test_the_preferred_width_never_exceeds_its_cap(cap: int) -> None:
    assert preferred_header_width("Estimated Future Payout Schedule") <= 24
    assert balanced_wrap_width("x " * 60, max_cap=cap) <= cap
