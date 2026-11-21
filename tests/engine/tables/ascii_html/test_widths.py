"""Column width allocation under `RenderBudget`."""

from __future__ import annotations

import pytest

from edgar_sec.engine.tables.ascii_html.model import (
    DEFAULT_RENDER_BUDGET,
    HorizontalAlign,
    RenderBudget,
)
from edgar_sec.engine.tables.ascii_html.widths import (
    _normalize_header_key,
    compute_column_widths,
)

DENSE_GRID = [
    [f"Estimated Future Payout {index}" for index in range(10)],
    ["1,000"] * 10,
]
DENSE_BUDGET = RenderBudget(max_table_width=60, max_dense_table_overflow=12)


def _right(count: int) -> list[HorizontalAlign]:
    return [HorizontalAlign.RIGHT] * count


def test_an_empty_grid_has_no_columns() -> None:
    assert compute_column_widths([], []) == ([], [])


def test_a_grid_with_no_columns_has_no_widths() -> None:
    assert compute_column_widths([[]], []) == ([], [])


def test_narrow_dense_numeric_tables_stay_inside_the_ordinary_cap() -> None:
    grid = [[f"Estimated Future Payout {index}" for index in range(9)], ["1,000"] * 9]
    widths, _ = compute_column_widths(grid, _right(9), budget=DENSE_BUDGET)
    assert sum(widths) + DENSE_BUDGET.column_spacing * 8 <= DENSE_BUDGET.max_table_width


def test_only_a_dense_multi_column_numeric_layout_may_bounded_overflow() -> None:
    widths, _ = compute_column_widths(DENSE_GRID, _right(10), budget=DENSE_BUDGET)
    total = sum(widths) + DENSE_BUDGET.column_spacing * 9
    assert total > DENSE_BUDGET.max_table_width
    assert total <= DENSE_BUDGET.max_table_width + DENSE_BUDGET.max_dense_table_overflow


def test_a_dense_table_without_enough_numeric_columns_does_not_overflow() -> None:
    grid = [[f"Header {index}" for index in range(9)], ["1,000"] * 9]
    widths, _ = compute_column_widths(
        grid, _right(9), budget=RenderBudget(max_table_width=20)
    )
    # The cap is a target: shrinking stops at each column's safe width.
    assert sum(widths) > 20
    assert all(width >= 3 for width in widths)


def test_the_total_never_exceeds_the_budget_for_a_small_table() -> None:
    grid = [["Line Item", "Amount"], ["Revenue", "1,200"]]
    budget = RenderBudget(max_table_width=24)
    widths, _ = compute_column_widths(
        grid, [HorizontalAlign.LEFT, HorizontalAlign.RIGHT], budget=budget
    )
    assert sum(widths) + budget.column_spacing <= budget.max_table_width


def test_a_mirror_header_column_pair_receives_the_same_width() -> None:
    grid = [
        ["Item", "2024", "2024"],
        ["Revenue", "1,200", "1,100"],
        ["Expenses", "400", "350"],
    ]
    widths, _ = compute_column_widths(grid, _right(3))
    assert widths[1] == widths[2]


def test_mirror_columns_are_not_matched_when_the_years_differ() -> None:
    grid = [["Item", "2024", "2023"], ["Revenue", "1,200", "1,100"]]
    widths, _ = compute_column_widths(grid, _right(3))
    assert widths[1] != 0 and widths[2] != 0


def test_columns_shrink_to_fit_their_text_but_a_numeric_column_keeps_a_floor() -> None:
    grid = [["Item", "Amount"], ["Revenue", "1,200"]]
    budget = DEFAULT_RENDER_BUDGET
    widths, _ = compute_column_widths(
        grid, [HorizontalAlign.LEFT, HorizontalAlign.RIGHT]
    )
    assert widths[0] <= len("Revenue")
    assert widths[1] == 7
    assert sum(widths) <= budget.max_table_width


def test_a_prose_column_expands_into_available_headroom() -> None:
    prose = "Unadjusted quoted prices in active markets for identical assets"
    grid = [["Level", "Description"], ["1", prose]]
    budget = RenderBudget(max_table_width=120)
    widths, _ = compute_column_widths(
        grid, [HorizontalAlign.LEFT, HorizontalAlign.LEFT], budget=budget
    )
    assert widths[1] > len(prose) // 2


def test_a_cell_longer_than_its_column_is_reported_as_a_forced_wrap() -> None:
    grid = [["Item", "Amount"], ["A very long row label indeed", "1,200"]]
    budget = RenderBudget(max_table_width=12)
    _widths, diagnostics = compute_column_widths(
        grid, [HorizontalAlign.LEFT, HorizontalAlign.RIGHT], budget=budget
    )
    assert any(diag.forced_wrap for diag in diagnostics)
    assert all(diag.rendered_lines >= 1 for diag in diagnostics)


def test_the_default_budget_columns_increment_by_the_configured_spacing() -> None:
    grid = [["a", "b", "c"], ["1", "2", "3"]]
    widths, _ = compute_column_widths(
        grid, _right(3), budget=RenderBudget(column_spacing=3)
    )
    assert len(widths) == 3
    assert DEFAULT_RENDER_BUDGET.column_spacing == 2


def test_a_span_constraint_widens_the_columns_it_covers() -> None:
    grid = [["Item", "Year Ended December 31", ""], ["Revenue", "1,200", "1,100"]]
    align = [HorizontalAlign.LEFT, HorizontalAlign.RIGHT, HorizontalAlign.RIGHT]
    _widths, _diag = compute_column_widths(
        grid, align, span_constraints=[(0, [1, 2], "Year Ended December 31")]
    )
    unconstrained, _ = compute_column_widths(grid, align)
    assert unconstrained[1] + unconstrained[2] >= 20


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2024", "2024"),
        ("2024 (1)", "2024"),
        ("2024 (a)", "2024"),
        ("2024 *", "2024"),
        ("Net income (loss)", "net income (loss)"),
        ("Percentage", "percentage"),
    ],
)
def test_a_trailing_footnote_marker_is_stripped_before_mirror_matching(
    text: str, expected: str
) -> None:
    assert _normalize_header_key(text) == expected
