"""Render block grouping, span constraints, and the affix fusion passes."""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.blocks import (
    RenderBlock,
    align_terminal_numeric_headers,
    build_row_blocks,
    expand_numeric_blocks_to_header_bands,
    extract_raw_grids_and_spans,
    fuse_data_affix_blocks,
    fuse_empty_header_span_blocks,
    fuse_header_suffix_blocks,
)
from edgar_sec.engine.tables.ascii_html.model import (
    DEFAULT_RENDER_BUDGET,
    BorderStyle,
    HorizontalAlign,
    RenderBudget,
    SourceCell,
)


def _cell(text: str, **kwargs: object) -> SourceCell:
    return SourceCell(
        row_index=0,
        source_col_index=0,
        tag="td",
        text=text,
        **kwargs,  # type: ignore[arg-type]
    )


def _block(
    cols: list[int],
    text: str,
    width: int = 4,
    cell: SourceCell | None = None,
    alignment: HorizontalAlign = HorizontalAlign.LEFT,
) -> RenderBlock:
    return RenderBlock(
        cell=cell, span_cols=cols, width=width, alignment=alignment, text=text
    )


def test_a_single_column_row_yields_one_constraint_free_grid_row() -> None:
    matrix = [[_cell("a")], [_cell("b")]]
    raw, single, constraints = extract_raw_grids_and_spans(matrix, [0])
    assert raw == [["a"], ["b"]]
    assert single == [["a"], ["b"]]
    assert constraints == []


def test_a_colspan_row_records_the_span_and_blanks_the_continuation_grid() -> None:
    shared = _cell("total", colspan=2)
    matrix = [[shared, shared], [_cell("a"), _cell("b")]]
    raw, single, constraints = extract_raw_grids_and_spans(matrix, [0, 1])
    assert raw[0] == ["total", ""]
    assert single[0] == ["", ""]
    assert constraints == [(0, [0, 1], "total")]


def test_a_rowspan_continuation_row_is_blank_so_the_text_is_not_repeated() -> None:
    shared = _cell("Cost", rowspan=2)
    matrix = [[shared, _cell("400")], [shared, _cell("350")]]
    raw, _single, _constraints = extract_raw_grids_and_spans(matrix, [0, 1])
    assert raw == [["Cost", "400"], ["", "350"]]


def test_consecutive_columns_owned_by_one_cell_form_a_single_block() -> None:
    shared = _cell("total", colspan=2)
    matrix = [[shared, shared]]
    blocks = build_row_blocks(
        matrix,
        0,
        [0, 1],
        [0, 1],
        [4, 4],
        [HorizontalAlign.LEFT] * 2,
        [["total", ""]],
        DEFAULT_RENDER_BUDGET,
    )
    assert len(blocks) == 1
    assert blocks[0].span_cols == [0, 1]
    assert blocks[0].width == 4 + DEFAULT_RENDER_BUDGET.column_spacing + 4


def test_a_multi_column_block_is_centered_unless_the_cell_says_otherwise() -> None:
    shared = _cell("total", colspan=2)
    matrix = [[shared, shared]]
    blocks = build_row_blocks(
        matrix,
        0,
        [0, 1],
        [0, 1],
        [4, 4],
        [HorizontalAlign.LEFT] * 2,
        [["total", ""]],
        DEFAULT_RENDER_BUDGET,
    )
    assert blocks[0].alignment is HorizontalAlign.CENTER


def test_a_data_row_fuses_a_currency_prefix_into_the_amount() -> None:
    blocks = [_block([0], "$"), _block([1], "1,200", width=5)]
    fused = fuse_data_affix_blocks(blocks, 1, 1, {0}, set(), DEFAULT_RENDER_BUDGET)
    assert len(fused) == 1
    assert fused[0].text == "$ 1,200"
    assert fused[0].alignment is HorizontalAlign.RIGHT


def test_a_header_row_is_never_fused_because_affix_columns_mean_nothing_there() -> None:
    blocks = [_block([0], "$"), _block([1], "Amount", width=6)]
    assert (
        fuse_data_affix_blocks(blocks, 0, 1, {0}, set(), DEFAULT_RENDER_BUDGET)
        == blocks
    )


def test_a_standalone_hyphen_does_not_attach_to_the_following_number() -> None:
    blocks = [_block([0], "-"), _block([1], "250,000", width=7)]
    fused = fuse_data_affix_blocks(blocks, 1, 1, {0}, set(), DEFAULT_RENDER_BUDGET)
    assert len(fused) == 2
    assert fused[0].text == "-"


def test_a_closing_parenthesis_fuses_directly_with_no_space() -> None:
    blocks = [_block([0], "(127,110", width=8), _block([1], ")", width=1)]
    fused = fuse_data_affix_blocks(blocks, 1, 1, set(), {1}, DEFAULT_RENDER_BUDGET)
    assert len(fused) == 1
    assert fused[0].text == "(127,110)"


def test_a_percent_suffix_fuses_with_a_space() -> None:
    blocks = [_block([0], "5", width=1), _block([1], "%", width=1)]
    fused = fuse_data_affix_blocks(blocks, 1, 1, set(), {1}, DEFAULT_RENDER_BUDGET)
    assert len(fused) == 1
    assert fused[0].text == "5 %"


def test_a_header_extends_across_an_empty_accounting_suffix_band() -> None:
    blocks = [_block([0, 1], "2024", width=8), _block([2], "", width=1)]
    fused = fuse_header_suffix_blocks(blocks, 0, 1, {2}, DEFAULT_RENDER_BUDGET)
    assert len(fused) == 1
    assert fused[0].span_cols == [0, 1, 2]


def test_a_header_does_not_extend_across_a_band_that_carries_content() -> None:
    blocks = [_block([0, 1], "2024", width=8), _block([2], "(1)", width=3)]
    assert fuse_header_suffix_blocks(blocks, 0, 1, {2}, DEFAULT_RENDER_BUDGET) == blocks


def test_an_empty_data_row_sub_block_fuses_under_its_parent_header_span() -> None:
    blocks = [_block([0, 1], "", width=6), _block([2], "1,200", width=5)]
    fused = fuse_empty_header_span_blocks(
        blocks, 2, 1, [{0, 1, 2}], DEFAULT_RENDER_BUDGET
    )
    assert len(fused) == 1
    assert fused[0].text == "1,200"


def test_a_protected_span_is_never_absorbed_into_a_neighbour() -> None:
    blocks = [_block([0, 1], "", width=6), _block([2], "1,200", width=5)]
    fused = fuse_empty_header_span_blocks(
        blocks, 2, 1, [{0, 1, 2}], DEFAULT_RENDER_BUDGET, protected_spans={(0, 1)}
    )
    assert len(fused) == 2


def test_a_range_marker_block_is_never_absorbed() -> None:
    blocks = [_block([0, 1], "", width=6), _block([2], "-", width=1)]
    fused = fuse_empty_header_span_blocks(
        blocks, 2, 1, [{0, 1, 2}], DEFAULT_RENDER_BUDGET
    )
    assert len(fused) == 2


def test_a_combined_numeric_value_expands_across_its_three_column_band() -> None:
    blocks = [
        _block([0], "", width=4),
        _block([1], "$14,164", width=7),
        _block([2], "", width=1),
    ]
    expanded = expand_numeric_blocks_to_header_bands(
        blocks, [{0, 1, 2}], DEFAULT_RENDER_BUDGET
    )
    assert len(expanded) == 1
    assert expanded[0].text == "$14,164"
    assert expanded[0].alignment is HorizontalAlign.RIGHT


def test_a_band_with_two_populated_blocks_is_left_alone() -> None:
    blocks = [
        _block([0], "1,200", width=5),
        _block([1], "1,100", width=5),
        _block([2], "", width=1),
    ]
    assert (
        expand_numeric_blocks_to_header_bands(
            blocks, [{0, 1, 2}], DEFAULT_RENDER_BUDGET
        )
        == blocks
    )


def test_a_terminal_subheader_aligns_to_the_numeric_edge_not_the_micro_columns() -> (
    None
):
    blocks = [_block([0], "$", width=1), _block([0, 1], "Amount", width=7)]
    aligned = align_terminal_numeric_headers(blocks, 2, {2}, {1}, {0})
    assert aligned[1].alignment is HorizontalAlign.RIGHT
    assert aligned[0].alignment is HorizontalAlign.LEFT


def test_a_wide_terminal_header_is_left_centered() -> None:
    blocks = [_block([0, 1, 2, 3], "Total amounts", width=20)]
    aligned = align_terminal_numeric_headers(blocks, 2, {2}, {3}, {0})
    assert aligned[0].alignment is HorizontalAlign.LEFT


def test_render_budget_column_spacing_participates_in_block_widths() -> None:
    tight = RenderBudget(column_spacing=1)
    assert _block([0, 1], "x", width=4).width + tight.column_spacing == 5
    assert DEFAULT_RENDER_BUDGET.column_spacing == 2
    assert BorderStyle.SOLID is not None
