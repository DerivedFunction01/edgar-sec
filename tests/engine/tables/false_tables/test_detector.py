"""Layout-grid classification: the vectors that decide retain versus unwrap.

Every expectation here was taken from the V1 reference tree, so a change in
verdict is a change in product behaviour rather than a test needing a rewrite.
"""

from __future__ import annotations

import pytest

from edgar_sec.engine.tables.false_tables.detector import (
    _is_prose_marker,
    _is_prose_text,
    _is_single_column_prose,
    _is_unambiguous_list_marker,
    _marker_candidates,
    is_false_grid,
    is_false_table,
)

FOOTNOTE_GRID = (
    ("[1]", "All amounts in thousands, except share and per share amounts."),
    ("[2]", "Reflects 34 securities."),
)
BULLET_GRID = (("•", "We operate in a highly competitive market."),)
NUMBERED_MULTI = (
    ("1.", "Introduction"),
    ("2.", "Risk Factors"),
    ("3.", "Selected Financial Data"),
    ("4.", "Mine Safety"),
    ("5.", "Management's Discussion"),
)
EXHIBIT_GRID = (
    ("3.1", "Charter of the Registrant, as amended."),
    ("3.2", "Certificate of Incorporation."),
)
SIGNATURE_GRID = (
    ("Pursuant to the requirements of Section 13 or 15(d) of the Act.", "Date"),
    ("Registrant has duly caused this report to be signed.", "Registrant"),
)
ITEM_REFERENCE_GRID = (
    ("ITEM 1. BUSINESS", "1"),
    ("ITEM 2. PROPERTIES", "2"),
)


def _rendered(*lines: str) -> str:
    return "<TABLE>" + "\n".join(lines) + "</TABLE>"


def test_an_empty_grid_is_always_a_false_table() -> None:
    assert is_false_grid(()) is True
    assert is_false_grid((("", ""),)) is True
    assert is_false_table(_rendered("")) is True


def test_a_single_bullet_row_is_a_prose_table() -> None:
    assert is_false_grid(BULLET_GRID) is True


def test_five_ordered_prose_rows_are_still_a_prose_table() -> None:
    assert is_false_grid(NUMBERED_MULTI) is True


def test_a_three_column_ordered_prose_grid_is_still_unwrapped() -> None:
    grid = (("1.", "Revenue", "1,000"), ("2.", "Expenses", "400"))
    assert is_false_grid(grid) is True


def test_a_footnote_marker_table_is_retained() -> None:
    assert is_false_grid(FOOTNOTE_GRID) is False


def test_an_exhibit_index_is_unwrapped() -> None:
    assert is_false_grid(EXHIBIT_GRID) is True


def test_a_signatory_block_is_retained() -> None:
    assert is_false_grid(SIGNATURE_GRID) is False


def test_a_two_column_financial_table_is_retained() -> None:
    assert (
        is_false_grid((("Total revenues", "1,200"), ("Cost of sales", "400"))) is False
    )


def test_a_three_column_financial_table_is_retained() -> None:
    grid = (
        ("Total revenues", "1,200", "1,100"),
        ("Cost of sales", "400", "350"),
    )
    assert is_false_grid(grid) is False


def test_a_three_column_grid_with_no_markers_is_retained() -> None:
    assert is_false_grid((("a", "b", "c"),)) is False


def test_a_single_column_of_prose_is_unwrapped() -> None:
    assert is_false_grid((("Some narrative prose line.",),)) is True


def test_a_single_column_of_one_number_is_also_unwrapped() -> None:
    assert is_false_grid((("1,200",),)) is True


def test_a_lead_in_prose_row_followed_by_bullets_is_unwrapped() -> None:
    grid = (
        ("The following risk factors apply:", ""),
        ("•", "Competition."),
        ("•", "Regulation."),
    )
    assert is_false_grid(grid) is True


def test_a_numeric_value_column_blocks_the_lead_in_prose_unwrap() -> None:
    grid = (("The following risk factors apply:", ""), ("•", "1,200"))
    assert is_false_grid(grid) is False


def test_a_toc_row_grid_is_retained() -> None:
    assert is_false_grid((("Item 1. Business", "10"),)) is False


def test_an_item_reference_grid_is_retained() -> None:
    assert is_false_grid(ITEM_REFERENCE_GRID) is False


def test_an_item_reference_grid_with_amounts_is_still_retained() -> None:
    grid = (("ITEM 1. BUSINESS", "1,000"), ("ITEM 2. PROPERTIES", "2,000"))
    assert is_false_grid(grid) is False


@pytest.mark.parametrize("page", ["10", "F-1", "2"])
def test_a_bare_numbered_heading_pair_is_ordered_prose_and_is_unwrapped(
    page: str,
) -> None:
    # A bare `1.` prefix reads as an ordered list marker, so the row pair is
    # prose even with a page column. Retention needs the `ITEM n` prefix, which
    # the table-of-contents predicates recognize and an ordered marker does not.
    grid = (("1. Risk Factors", page), ("2. Properties", page))
    assert is_false_grid(grid) is True
    assert (
        is_false_grid((("ITEM 1. RISK FACTORS", page), ("ITEM 2. PROPERTIES", page)))
        is False
    )


def test_a_table_with_no_content_is_never_a_layout_grid() -> None:
    assert is_false_grid(()) is True
    assert is_false_grid((("", "", ""),)) is True


# --- is_false_table: rendered text, no geometry ----------------------------


def test_a_rendered_toc_item_row_with_a_page_number_is_retained() -> None:
    assert (
        is_false_table(
            _rendered("Item 1. Business ................................ 10")
        )
        is False
    )


def test_a_rendered_toc_row_with_a_namespaced_page_number_is_retained() -> None:
    assert (
        is_false_table(
            _rendered("Item 1. Business ................................ F-1")
        )
        is False
    )


def test_a_rendered_toc_row_with_a_dot_leader_is_retained() -> None:
    assert (
        is_false_table(_rendered("ITEM 1. BUSINESS .......................... 1"))
        is False
    )


def test_a_rendered_financial_table_is_retained() -> None:
    assert (
        is_false_table(_rendered("Total revenues 1,200 1,100", "Cost of sales 400 350"))
        is False
    )


def test_a_rendered_bare_separator_row_is_retained() -> None:
    assert is_false_table(_rendered("---------------")) is False


def test_a_rendered_single_prose_line_is_unwrapped() -> None:
    assert (
        is_false_table(_rendered("The Company was incorporated in Delaware.")) is True
    )


def test_a_rendered_part_heading_alone_does_not_match_a_toc_row() -> None:
    assert is_false_table(_rendered("PART I")) is True


def test_a_rendered_multi_line_block_is_never_unwrapped() -> None:
    assert is_false_table(_rendered("line one", "line two")) is False


def test_raw_html_inside_a_table_wrapper_does_not_read_as_a_toc_row() -> None:
    # The rendered-text path strips only the `<TABLE>` wrapper, so a body that
    # still carries `<TR>`/`<TD>` never matches the leading-heading patterns.
    # Callers pass rendered text, and geometry is preferred when available.
    body = (
        "<TABLE><TR><TD>Item 1. Business "
        "................................ 10</TD></TR></TABLE>"
    )
    assert is_false_table(body) is True
    assert (
        is_false_table(_rendered("Item 1. Business ........................ 10"))
        is False
    )


def test_geometry_overrides_the_rendered_text_when_it_is_supplied() -> None:
    from edgar_sec.engine.tables.ascii_html.converter import convert_html_table
    from edgar_sec.engine.tables.ascii_html.model import TableGeometry

    result = convert_html_table(
        "<table><tr><td>Revenue</td><td>1,200</td></tr>"
        "<tr><td>Expenses</td><td>400</td></tr></table>"
    )
    geometry = TableGeometry(table_index=0, render_result=result)
    assert is_false_table(_rendered("a single line"), geometry) is False


# --- private predicate vocabulary -------------------------------------------


def test_prose_marker_helpers_agree_on_bullets_and_footnotes() -> None:
    assert _is_prose_marker("•") is True
    assert _is_prose_marker("(1)") is True
    assert _is_prose_marker("Revenue") is False
    assert _is_unambiguous_list_marker("(1)") is True
    assert _is_unambiguous_list_marker("1.") is True
    assert _is_prose_text("Revenue was flat") is True
    assert _is_prose_text("1,200") is False
    assert _is_single_column_prose(["a word", "two words"]) is True
    assert _is_single_column_prose(["1,200"]) is True
    assert _is_single_column_prose(["1,200", "Revenue"]) is False


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("1. Revenue", "number"),
        ("IV. Part", "roman"),
        ("a) Alpha", "letter"),
        ("(1) Footnote", "number"),
        ("(iv) Roman", "roman"),
        ("(a) Letter", "letter"),
    ],
)
def test_marker_candidates_cover_numbers_roman_numerals_and_letters(
    cell: str, expected: str
) -> None:
    families = {family for family, _value, _rest in _marker_candidates(cell)}
    assert expected in families


def test_an_ambiguous_single_roman_letter_offers_both_readings() -> None:
    assert len(_marker_candidates("i) Item")) == 2
    assert len(_marker_candidates("iv) Item")) == 1


def test_a_non_marker_cell_offers_no_candidates() -> None:
    assert _marker_candidates("Revenue") == []


def test_a_marker_with_nothing_after_it_still_yields_an_empty_rest() -> None:
    assert _marker_candidates("1.")[0][2] == ""
