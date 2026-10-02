"""Divider formatting, affix gap repair, and phantom fragment pruning."""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.blocks import RenderBlock
from edgar_sec.engine.tables.ascii_html.columns import is_affix_footnote_token
from edgar_sec.engine.tables.ascii_html.dividers import (
    format_row_divider,
    format_top_divider,
    heal_divider_lines_from_templates,
    prune_unanchored_divider_fragments,
    repair_rendered_affix_columns,
)
from edgar_sec.engine.tables.ascii_html.model import (
    BorderStyle,
    HorizontalAlign,
    RenderBudget,
)

BUDGET = RenderBudget(column_spacing=2)
COL_SEP = "  "


def _block(cols: list[int], width: int, text: str = "x") -> RenderBlock:
    return RenderBlock(
        cell=None,
        span_cols=cols,
        width=width,
        alignment=HorizontalAlign.LEFT,
        text=text,
    )


def test_no_top_border_means_no_top_divider() -> None:
    assert format_top_divider([(None, [0], 4)], {}, COL_SEP) is None


def test_a_top_border_renders_one_run_per_row_zero_block() -> None:
    divider = format_top_divider([(None, [0], 4)], {0: {0: BorderStyle.SOLID}}, COL_SEP)
    assert divider == "----"


def test_a_double_top_border_renders_equals_signs() -> None:
    divider = format_top_divider(
        [(None, [0], 3)], {0: {0: BorderStyle.DOUBLE}}, COL_SEP
    )
    assert divider == "==="


def test_a_block_with_no_border_contributes_spaces_that_are_then_rstripped() -> None:
    divider = format_top_divider(
        [(None, [0], 4), (None, [1], 4)],
        {0: {0: BorderStyle.SOLID, 1: BorderStyle.NONE}},
        COL_SEP,
    )
    assert divider == "----"


def test_a_row_with_no_border_and_no_header_edge_has_no_divider() -> None:
    blocks = [_block([0], 4)]
    assert (
        format_row_divider(
            blocks,
            0,
            0,
            BorderStyle.SOLID,
            {},
            {},
            BUDGET,
            COL_SEP,
            set(),
            set(),
            False,
        )
        is None
    )


def test_the_header_bottom_always_draws_a_divider_under_populated_blocks() -> None:
    divider = format_row_divider(
        [_block([0], 4)],
        0,
        1,
        BorderStyle.SOLID,
        {},
        {},
        BUDGET,
        COL_SEP,
        set(),
        set(),
        False,
    )
    assert divider == "----"


def test_an_empty_header_block_under_the_header_edge_draws_nothing() -> None:
    divider = format_row_divider(
        [_block([0], 4, text="")],
        0,
        1,
        BorderStyle.SOLID,
        {},
        {},
        BUDGET,
        COL_SEP,
        set(),
        set(),
        False,
    )
    assert divider is None


def test_a_double_header_divider_uses_equals_signs() -> None:
    divider = format_row_divider(
        [_block([0], 3)],
        0,
        1,
        BorderStyle.DOUBLE,
        {},
        {},
        BUDGET,
        COL_SEP,
        set(),
        set(),
        False,
    )
    assert divider == "==="


def test_column_gaps_are_preserved_between_divider_runs() -> None:
    divider = format_row_divider(
        [_block([0], 4), _block([1], 4)],
        0,
        1,
        BorderStyle.SOLID,
        {},
        {},
        BUDGET,
        COL_SEP,
        set(),
        set(),
        False,
    )
    assert divider == "----  ----"


def test_a_row_border_on_the_following_row_still_draws_a_divider() -> None:
    divider = format_row_divider(
        [_block([0], 4)],
        0,
        0,
        BorderStyle.SOLID,
        {},
        {1: {0: BorderStyle.SOLID}},
        BUDGET,
        COL_SEP,
        set(),
        set(),
        False,
    )
    assert divider == "----"


def test_repairing_an_affix_column_restores_its_mark_between_two_runs() -> None:
    lines = ["$ 1,200", "-----  -----", "$ 1,100", "-----  -----"]
    repair_rendered_affix_columns(lines)
    assert lines[1] == "--" + "-" + "--  -----"


def test_repairing_is_a_no_op_when_no_affix_token_appears() -> None:
    lines = ["Revenue  1,200", "--------  -------"]
    before = list(lines)
    repair_rendered_affix_columns(lines)
    assert lines == before


def test_a_fragmented_divider_borrows_marks_from_an_equal_length_template() -> None:
    lines = ["<TABLE>", "--  --", "-   --", "</TABLE>"]
    heal_divider_lines_from_templates(lines)
    assert lines[2] == "--  --"


def test_a_divider_with_no_equal_length_template_is_untouched() -> None:
    lines = ["<TABLE>", "-" * 10, "  " + "-" * 3, "</TABLE>"]
    before = list(lines)
    heal_divider_lines_from_templates(lines)
    assert lines == before


def test_a_wide_gap_cannot_be_healed_because_one_fill_run_would_be_too_long() -> None:
    lines = ["<TABLE>", "--  --", "-      --", "</TABLE>"]
    before = list(lines)
    heal_divider_lines_from_templates(lines)
    assert lines == before


def test_healing_does_nothing_with_fewer_than_two_dividers() -> None:
    lines = ["<TABLE>", "-" * 10, "</TABLE>"]
    before = list(lines)
    heal_divider_lines_from_templates(lines)
    assert lines == before


def test_an_orphaned_short_fragment_is_pruned_when_no_text_row_anchors_it() -> None:
    lines = [
        "<TABLE>",
        "Item  Amount",
        "-" * 5 + "   " + "-" * 5,
        "Revenue  1,200",
        "</TABLE>",
    ]
    prune_unanchored_divider_fragments(lines)
    assert lines[2] == "-" * 5 + "   " + "-" * 5


def test_a_fragment_anchored_by_a_text_row_is_kept() -> None:
    lines = ["<TABLE>", "a  bbb  ccc", "-  ---  ---", "</TABLE>"]
    prune_unanchored_divider_fragments(lines)
    assert lines[2] == "-  ---  ---"


def test_a_zero_width_column_fragment_is_pruned_but_its_neighbour_survives() -> None:
    lines = ["<TABLE>", "a        ccc", "-  ---  ---", "</TABLE>"]
    prune_unanchored_divider_fragments(lines)
    assert lines[2] == "-       ---"


def test_pruning_leaves_a_table_with_no_text_rows_alone() -> None:
    lines = ["<TABLE>", "- -", "</TABLE>"]
    before = list(lines)
    prune_unanchored_divider_fragments(lines)
    assert lines == before


def test_the_affix_footnote_predicate_is_injectable_into_row_dividers() -> None:
    blocks = [_block([0], 4)]
    with_fn = format_row_divider(
        blocks,
        1,
        0,
        BorderStyle.SOLID,
        {1: {0: BorderStyle.SOLID}},
        {},
        BUDGET,
        COL_SEP,
        set(),
        set(),
        True,
        is_affix_footnote_token_fn=is_affix_footnote_token,
    )
    without_fn = format_row_divider(
        blocks,
        1,
        0,
        BorderStyle.SOLID,
        {1: {0: BorderStyle.SOLID}},
        {},
        BUDGET,
        COL_SEP,
        set(),
        set(),
        True,
    )
    assert with_fn == without_fn == "----"
