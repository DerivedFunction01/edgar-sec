"""Tests for the split-parenthesis geometry canonicalization."""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.converter import convert_html_table
from edgar_sec.engine.tables.ascii_html.parens import merge_split_paren_cells


def test_next_cell_paren_merges() -> None:
    rows = [["Interest expense", "(8,314", ")"]]
    assert merge_split_paren_cells(rows) == [["Interest expense", "(8,314)", ""]]


def test_empty_cell_gap_merges() -> None:
    rows = [["Interest expense", "(8,314", "", ")"]]
    assert merge_split_paren_cells(rows) == [["Interest expense", "(8,314)", "", ""]]


def test_checkerboard_row_merges_both_pairs() -> None:
    rows = [["Interest expense", "(8,314", "", ")", "(7,691", "", ")"]]
    assert merge_split_paren_cells(rows) == [
        ["Interest expense", "(8,314)", "", "", "(7,691)", "", ""]
    ]


def test_benign_suffix_stays_as_its_own_cell() -> None:
    for suffix in ("%", "*", "†", "‡"):
        rows = [["(1,234", f"){suffix}"]]
        assert merge_split_paren_cells(rows) == [["(1,234)", suffix]]


def test_zero_value_still_merges() -> None:
    assert merge_split_paren_cells([["(0", ")"]]) == [["(0)", ""]]


def test_bare_paren_without_value_open_stays() -> None:
    rows = [["Label", ")"], [")", "5"]]
    assert merge_split_paren_cells(rows) == rows


def test_non_digit_open_cell_never_merges() -> None:
    rows = [["(State or other jurisdiction", ")"], ["(A", "", ")"]]
    assert merge_split_paren_cells(rows) == rows


def test_fused_footnote_close_does_not_merge() -> None:
    for close in (")(2)(4)", ")**", ")5"):
        rows = [["(1,234", close]]
        assert merge_split_paren_cells(rows) == rows


def test_balanced_or_value_neighbour_is_not_consumed() -> None:
    rows = [["(1,234", "(5,678)"], ["(1,234", "5,678)"], ["(1,234", "$"]]
    assert merge_split_paren_cells(rows) == rows


def test_no_close_in_row_stays_as_printed() -> None:
    rows = [["(979,922", "", ""], ["(1,234", "x", "", ")"]]
    assert merge_split_paren_cells(rows) == rows


def test_already_balanced_cell_untouched() -> None:
    rows = [["(136)", ")"]]
    assert merge_split_paren_cells(rows) == rows


def test_input_rows_are_not_mutated() -> None:
    rows = [["(8,314", ")"]]
    merge_split_paren_cells(rows)
    assert rows == [["(8,314", ")"]]


def test_converted_geometry_rows_are_merged() -> None:
    html = (
        "<table>"
        "<tr><td>Interest expense</td><td>(8,314</td><td></td><td>)</td></tr>"
        "<tr><td>Net sales</td><td>619,163</td><td></td><td></td></tr>"
        "</table>"
    )
    result = convert_html_table(html)
    assert any("(8,314)" in row for row in result.resolved_grid.rows)
    assert not any(
        cell == "(8,314" for row in result.resolved_grid.rows for cell in row
    )
