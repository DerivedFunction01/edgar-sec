"""Unwrapping a rejected grid and rewriting the surrounding text."""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.converter import (
    convert_html_tables_to_ascii_with_metadata,
)
from edgar_sec.engine.tables.false_tables.unwrapper import (
    _is_list_item,
    _join_prose_rows,
    cleanup_false_tables_with_metadata,
    unwrap_grid,
)

NUMBERED_GRID = (
    ("1.", "Financial Statements and Supplementary Data."),
    ("2.", "Properties."),
)
BULLET_GRID = (
    ("•", "Competition."),
    ("•", "Regulation."),
)
PROSE_GRID = (
    ("The following risk factors apply:", ""),
    ("We operate in a competitive market.", "and are subject to regulation."),
)


def test_unwrapping_an_empty_grid_yields_nothing() -> None:
    assert unwrap_grid(()) == ""
    assert unwrap_grid((("", ""),)) == ""


def test_a_numbered_grid_becomes_one_list_item_per_line() -> None:
    assert unwrap_grid(NUMBERED_GRID) == (
        "1. Financial Statements and Supplementary Data.\n2. Properties."
    )


def test_a_bullet_grid_becomes_one_bullet_per_line() -> None:
    assert unwrap_grid(BULLET_GRID) == "• Competition.\n• Regulation."


def test_a_prose_grid_joins_its_fragments_into_sentences() -> None:
    unwrapped = unwrap_grid(PROSE_GRID)
    assert (
        "We operate in a competitive market. and are subject to regulation."
        in unwrapped
    )
    # The lead-in row ends in a colon, which is continuation punctuation, so the
    # fragment after it starts on a new line rather than running on.
    assert unwrapped.startswith("The following risk factors apply:\n")


def test_a_prose_grid_without_continuation_punctuation_stays_on_one_line() -> None:
    grid = (("One fragment,", "another fragment."),)
    assert "\n" not in unwrap_grid(grid)


def test_empty_cells_are_dropped_before_joining() -> None:
    assert unwrap_grid((("a", "", "b"),)) == "a b"


def test_a_list_item_is_a_line_starting_with_a_bullet_marker() -> None:
    assert _is_list_item("• item") is True
    assert _is_list_item("1. item") is True
    assert _is_list_item("plain item") is False
    assert _is_list_item("   ") is False


def test_prose_rows_join_with_a_space_unless_the_previous_row_ends_a_sentence() -> None:
    assert _join_prose_rows([["one."], ["Two"]]) == "one.\nTwo"
    assert _join_prose_rows([["one,"], ["two"]]) == "one, two"


# --- cleanup_false_tables_with_metadata -------------------------------------


def test_text_without_a_table_is_returned_unchanged() -> None:
    assert cleanup_false_tables_with_metadata("just prose") == ("just prose", ())


def test_a_retained_table_is_left_byte_for_byte_alone() -> None:
    text = "<TABLE>Total revenues 1,200 1,100\nCost of sales 400 350</TABLE>"
    result, geometries = cleanup_false_tables_with_metadata(text)
    assert result == text
    assert geometries == ()


def test_a_single_prose_line_table_is_unwrapped() -> None:
    result, _geometries = cleanup_false_tables_with_metadata(
        "<TABLE>The Company was incorporated in Delaware.</TABLE>"
    )
    assert result == "The Company was incorporated in Delaware."


def test_a_surrounding_narrative_survives_the_unwrap() -> None:
    result, _geometries = cleanup_false_tables_with_metadata(
        "<p>Before.</p><TABLE>The Company was incorporated in Delaware.</TABLE><p>After.</p>"
    )
    assert "Before." in result
    assert "After." in result
    assert "incorporated in Delaware" in result
    assert "<TABLE>" not in result


def test_consecutive_unwrapped_tables_join_with_a_newline_when_both_are_list_items() -> (
    None
):
    result, _geometries = cleanup_false_tables_with_metadata(
        "<TABLE>• first bullet;</TABLE> <TABLE>• second bullet;</TABLE>"
    )
    assert result == "• first bullet;\n• second bullet;"


def test_consecutive_unwrapped_prose_tables_join_with_a_space() -> None:
    result, _geometries = cleanup_false_tables_with_metadata(
        "<TABLE>First fragment.</TABLE> <TABLE>Second fragment.</TABLE>"
    )
    assert result == "First fragment. Second fragment."


def test_retained_geometry_is_dropped_for_unwrapped_tables() -> None:
    text, geometries = convert_html_tables_to_ascii_with_metadata(
        "<table><tr><td>Revenue</td><td>1,200</td></tr>"
        "<tr><td>Expenses</td><td>400</td></tr></table>"
    )
    assert len(geometries) == 1
    result, kept = cleanup_false_tables_with_metadata(text, geometries)
    assert result == text
    assert len(kept) == 1

    prose_text, prose_geometries = convert_html_tables_to_ascii_with_metadata(
        "<table><tr><td>The Company was incorporated in Delaware in 1998.</td></tr></table>"
    )
    assert len(prose_geometries) == 1
    _result, kept_prose = cleanup_false_tables_with_metadata(
        prose_text, prose_geometries
    )
    assert kept_prose == ()


def test_footnote_context_never_unwraps_a_table_whose_second_column_is_label_shaped() -> (
    None
):
    text = (
        "<TABLE>\nLevel 1 - Unadjusted quoted prices in active markets.\n"
        "----------------------  --------------- ------------\n"
        "Total net revenue        $ 182,447 $ 177,556 $ 158,104\n</TABLE>"
    )
    result, _geometries = cleanup_false_tables_with_metadata(text)
    assert result == text
