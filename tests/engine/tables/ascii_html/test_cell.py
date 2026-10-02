"""Cell styling, whitespace normalization, wrapping, and column padding."""

from __future__ import annotations

import pytest

from edgar_sec.engine.document.html.tree import parse_html
from edgar_sec.engine.tables.ascii_html.cell import (
    format_cell_line,
    normalize_cell_whitespace,
    normalize_grid_indents,
    parse_dimension_px,
    parse_style_and_attributes,
    wrap_cell_text,
)
from edgar_sec.engine.tables.ascii_html.model import BorderStyle, HorizontalAlign

STYLED_TD = """
<table><tr>
  <td width="120" align="right" valign="top"
      style="padding-left: 8px; border-bottom: 2px solid #000; font-weight: bold;">
    <b>$1,234.50</b>
  </td>
</tr></table>
"""


def _style_of(html: str, selector: str = "td"):
    tree = parse_html(html)
    node = tree.css_first(selector)
    assert node is not None
    return parse_style_and_attributes(node)


def test_parse_dimension_converts_every_supported_unit_to_pixels() -> None:
    assert parse_dimension_px("100px") == (100.0, "px", False)
    assert parse_dimension_px("72pt")[0] == pytest.approx(96.0)
    assert parse_dimension_px("2in")[0] == pytest.approx(192.0)
    assert parse_dimension_px("50%") == (50.0, "%", True)
    assert parse_dimension_px("250") == (250.0, "px", False)
    assert parse_dimension_px("2.54cm")[0] == pytest.approx(96.0)


def test_parse_dimension_treats_missing_and_auto_as_unset() -> None:
    assert parse_dimension_px(None) == (None, "px", False)
    assert parse_dimension_px("") == (None, "px", False)
    assert parse_dimension_px("auto") == (None, "px", False)
    assert parse_dimension_px("wide") == (None, "px", False)


def test_html_attributes_and_inline_css_normalize_into_one_cell_style() -> None:
    style = _style_of(STYLED_TD)
    assert style.width == 120.0
    assert style.text_align is HorizontalAlign.RIGHT
    assert style.vertical_align.value == "top"
    assert style.padding_left == 8.0
    assert style.border_bottom_width == 2.0
    assert style.border_bottom_style is BorderStyle.SOLID
    assert style.border_bottom_color == "#000"
    assert style.is_bold is True


def test_typography_is_inherited_from_a_nested_bold_tag() -> None:
    assert _style_of(STYLED_TD).is_bold is True
    # A cell carrying no attributes at all short-circuits to the shared default
    # style, so a nested <b> in an attribute-free cell does not set the flag.
    assert _style_of("<table><tr><td><b>x</b></td></tr></table>").is_bold is False
    assert (
        _style_of('<table><tr><td style="color:red"><b>x</b></td></tr></table>').is_bold
        is True
    )
    assert (
        _style_of('<table><tr><td style="color:red">x</td></tr></table>').is_bold
        is False
    )


def test_italic_is_detected_from_a_nested_tag_or_an_inline_style() -> None:
    assert (
        _style_of(
            '<table><tr><td style="color:red"><i>x</i></td></tr></table>'
        ).is_italic
        is True
    )
    assert (
        _style_of(
            '<table><tr><td style="font-style:italic">x</td></tr></table>'
        ).is_italic
        is True
    )


def test_display_none_and_visibility_hidden_mark_a_cell_hidden() -> None:
    assert _style_of(
        '<table><tr><td style="display:none">x</td></tr></table>'
    ).is_hidden
    assert _style_of(
        '<table><tr><td style="visibility: hidden">x</td></tr></table>'
    ).is_hidden
    assert not _style_of(
        '<table><tr><td style="color:red">x</td></tr></table>'
    ).is_hidden


def test_the_bare_hidden_attribute_is_a_no_op() -> None:
    # The parser reports a valueless `hidden` attribute with a `None` value, and
    # the attribute map drops `None` values, so the `attrs.get("hidden")` probe
    # never fires. Hiding a cell therefore requires `display:none` or
    # `visibility:hidden` in the style attribute. Pinned because the behaviour is
    # surprising and must not change silently.
    assert parse_html("<table><tr><td hidden>x</td></tr></table>").css_first(
        "td"
    ).raw_node.attributes == {"hidden": None}
    assert (
        _style_of(
            '<table><tr><td style="color:red" hidden>x</td></tr></table>'
        ).is_hidden
        is False
    )


def test_border_and_cellpadding_attributes_apply_to_all_four_edges() -> None:
    style = _style_of(
        '<table border="1" cellpadding="4"><tr><td style="color:red">x</td></tr></table>',
        "table",
    )
    assert style.border_top_width == style.border_bottom_width == 1.0
    assert style.border_left_style is BorderStyle.SOLID
    assert style.padding_left == style.padding_right == 4.0


def test_a_cell_with_no_attributes_gets_the_shared_default_style() -> None:
    assert _style_of("<table><tr><td>x</td></tr></table>") is not None
    style = _style_of('<table><tr><td style="color:red">x</td></tr></table>')
    assert style.background_color is None


def test_dot_leaders_collapse_so_they_cannot_eat_a_column_budget() -> None:
    assert normalize_cell_whitespace("Operating" + "." * 40) == "Operating..."


def test_non_breaking_and_zero_width_characters_become_breakable_spaces() -> None:
    assert normalize_cell_whitespace("a\xa0bc") == "a bc"
    assert normalize_cell_whitespace("ab") == "ab"


def test_soft_wrapping_newlines_collapse_but_paragraphs_and_bullets_survive() -> None:
    assert normalize_cell_whitespace("one two\nthree four") == "one two three four"
    assert "\n" in normalize_cell_whitespace("first para.\n\nsecond para.")


def test_wrapping_breaks_on_word_boundaries_within_the_column_width() -> None:
    text = "Research and development expenses for current operating cycle"
    wrapped = wrap_cell_text(text, width=25)
    assert len(wrapped) >= 2
    assert all(len(line) <= 25 for line in wrapped)


def test_wrapping_breaks_hyphenated_tokens_at_the_hyphen_first() -> None:
    wrapped = wrap_cell_text("Fully taxable-equivalent adjustments (a)", width=10)
    assert len(wrapped) >= 3
    assert all(len(line) <= 10 for line in wrapped)
    assert wrapped[0] == "Fully"
    assert wrapped[1] == "taxable-"
    assert "taxable-eq" not in " ".join(wrapped)


def test_wrapping_never_splits_a_word_on_a_non_breaking_space() -> None:
    wrapped = wrap_cell_text(
        "Weighted\xa0Average Grant-Date\xa0Fair\xa0Value", width=20
    )
    assert not any(line.endswith("Gra") for line in wrapped)
    assert not any(line.startswith("nt-Date") for line in wrapped)
    assert "Grant-Date" in " ".join(wrapped)


@pytest.mark.parametrize(("text", "width"), [("", 10), ("   ", 10), ("x", 0)])
def test_wrapping_degenerate_inputs_still_yield_one_line(text: str, width: int) -> None:
    assert len(wrap_cell_text(text, width)) == 1


def test_format_cell_line_pads_to_exact_width_per_alignment() -> None:
    assert format_cell_line("1,234.50", 12, HorizontalAlign.RIGHT) == "    1,234.50"
    assert format_cell_line("ab", 6, HorizontalAlign.LEFT) == "ab    "
    assert format_cell_line("ab", 6, HorizontalAlign.CENTER) == "  ab  "


def test_format_cell_line_keeps_a_left_indent_but_strips_it_when_right_aligned() -> (
    None
):
    assert format_cell_line("   ab", 6, HorizontalAlign.LEFT) == "   ab "
    assert format_cell_line("   ab", 6, HorizontalAlign.RIGHT) == "    ab"


def test_format_cell_line_truncates_rather_than_overflowing() -> None:
    assert len(format_cell_line("abcdefgh", 4, HorizontalAlign.LEFT)) == 4
    assert len(format_cell_line("abcdefgh", 4, HorizontalAlign.RIGHT)) == 4


def test_uniform_indentation_is_removed_entirely() -> None:
    raw, single = normalize_grid_indents([["  a", "  b"]], [["  a", "  b"]])
    assert raw == [["a", "b"]]
    assert single == [["a", "b"]]


def test_distinct_indent_levels_normalize_to_discrete_two_space_tiers() -> None:
    raw, single = normalize_grid_indents(
        [["  a", "b"], ["    c", "  d"]], [["  a", "b"], ["    c", "  d"]]
    )
    assert single == [["a", "b"], ["  c", "  d"]]
    assert raw == single


def test_a_third_indent_level_is_capped_at_eight_spaces() -> None:
    _raw, single = normalize_grid_indents(
        [["a"], ["    b"], ["        c"]], [["a"], ["    b"], ["        c"]]
    )
    assert single[0][0] == "a"
    assert single[1][0] == "  b"
    assert single[2][0] == "    c"


def test_indent_normalization_passes_empty_grids_through() -> None:
    assert normalize_grid_indents([], []) == ([], [])
    assert normalize_grid_indents([[]], [[]]) == ([[]], [[]])
