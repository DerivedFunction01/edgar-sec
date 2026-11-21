"""Spacer retention policy, column resolution, and affix column identification."""

from __future__ import annotations

from edgar_sec.engine.document.html.tree import parse_html
from edgar_sec.engine.tables.ascii_html.columns import (
    identify_affix_columns,
    is_affix_footnote_token,
    is_structural_spacer,
    resolve_columns,
)
from edgar_sec.engine.tables.ascii_html.model import HorizontalAlign
from edgar_sec.engine.tables.ascii_html.spans import (
    build_span_matrix,
    extract_source_table,
)

SPACER_HTML = """
<table>
  <tr>
    <td>Line Item</td><td style="width: 15px;"></td><td>Amount</td><td></td>
  </tr>
  <tr>
    <td>Revenue</td><td style="width: 15px;"></td><td>1000</td><td></td>
  </tr>
</table>
"""

ALIGNED_HTML = """
<table>
  <tr>
    <th style="width: 200px;">Period</th>
    <th style="width: 100px;">Shares</th>
    <th>Price</th>
  </tr>
  <tr>
    <td>Q1 2024</td><td align="right">1,000</td><td align="right">$25.50</td>
  </tr>
</table>
"""


def _matrix(html: str):
    node = parse_html(html).css_first("table")
    assert node is not None
    source, _ = extract_source_table(node)
    return build_span_matrix(source)


def test_a_width_declared_spacer_is_retained_and_an_inert_one_is_pruned() -> None:
    matrix, _ = _matrix(SPACER_HTML)
    assert is_structural_spacer(1, matrix) is True
    assert is_structural_spacer(3, matrix) is False


def test_a_column_always_starting_a_cell_is_never_a_spacer() -> None:
    matrix, _ = _matrix("<table><tr><td>a</td><td>b</td></tr></table>")
    assert is_structural_spacer(0, matrix) is True
    assert is_structural_spacer(1, matrix) is True


def test_a_column_submerged_in_spans_on_every_row_is_pruned() -> None:
    from edgar_sec.engine.tables.ascii_html.model import SourceCell

    shared = SourceCell(row_index=0, source_col_index=0, tag="td", text="a", colspan=2)
    matrix = [[shared, shared]]
    assert is_structural_spacer(1, matrix) is False


def test_resolution_keeps_every_content_column_and_reports_no_spacers() -> None:
    matrix, _ = _matrix(ALIGNED_HTML)
    active, alignments, spacers = resolve_columns(matrix, [[None] * 3] * 2)
    assert active == [0, 1, 2]
    assert alignments[0] is HorizontalAlign.LEFT
    assert alignments[1] is HorizontalAlign.RIGHT
    assert alignments[2] is HorizontalAlign.RIGHT
    assert spacers == []


def test_resolution_of_an_empty_grid_is_empty() -> None:
    assert resolve_columns([], []) == ([], [], [])


def test_a_predominantly_numeric_column_is_right_aligned() -> None:
    matrix, _ = _matrix(
        "<table><tr><td>Revenue</td><td>1,200</td></tr>"
        "<tr><td>Expenses</td><td>400</td></tr></table>"
    )
    _active, alignments, _spacers = resolve_columns(matrix, [[None] * 2] * 2)
    assert alignments[1] is HorizontalAlign.RIGHT


def test_an_explicit_center_vote_wins_for_a_text_column() -> None:
    matrix, _ = _matrix(
        "<table><tr><td align='center'>Total</td><td align='center'>Amount</td></tr></table>"
    )
    _active, alignments, _spacers = resolve_columns(matrix, [[None] * 2] * 1)
    assert alignments[0] is HorizontalAlign.CENTER


def test_justify_is_read_as_left_rather_than_as_its_own_alignment() -> None:
    matrix, _ = _matrix(
        "<table><tr><td style='text-align:justify'>Prose</td>"
        "<td style='text-align:justify'>More</td></tr></table>"
    )
    _active, alignments, _spacers = resolve_columns(matrix, [[None] * 2] * 1)
    assert alignments[0] is HorizontalAlign.LEFT


def test_footnote_markers_are_recognized_by_shape() -> None:
    assert is_affix_footnote_token("*") is True
    assert is_affix_footnote_token("****") is True
    assert is_affix_footnote_token("(1)") is True
    assert is_affix_footnote_token("(a)") is True
    assert is_affix_footnote_token("") is False
    assert is_affix_footnote_token("note") is False
    assert is_affix_footnote_token("(too long)") is False


def test_a_currency_only_column_is_identified_as_a_prefix_column() -> None:
    matrix, _ = _matrix(
        "<table><tr><td>Revenue</td><td>$</td></tr>"
        "<tr><td>Expenses</td><td>$</td></tr></table>"
    )
    prefix, suffix = identify_affix_columns(matrix, [0, 1])
    assert 1 in prefix
    assert 1 not in suffix


def test_a_footnote_only_column_is_identified_as_a_suffix_column() -> None:
    matrix, _ = _matrix(
        "<table><tr><td>Revenue</td><td>1,200</td><td>(1)</td></tr>"
        "<tr><td>Expenses</td><td>400</td><td>(2)</td></tr></table>"
    )
    prefix, suffix = identify_affix_columns(matrix, [0, 1, 2])
    assert 2 in suffix
    assert 2 not in prefix


def test_a_mixed_content_column_is_neither_prefix_nor_suffix() -> None:
    matrix, _ = _matrix(
        "<table><tr><td>Revenue</td><td>1,200</td><td>note</td></tr></table>"
    )
    prefix, suffix = identify_affix_columns(matrix, [0, 1, 2])
    assert 2 not in prefix
    assert 2 not in suffix
