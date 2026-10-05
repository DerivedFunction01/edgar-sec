"""DOM extraction, span ownership, and nested table isolation."""

from __future__ import annotations

from edgar_sec.engine.document.html.tree import parse_html
from edgar_sec.engine.tables.ascii_html.model import HorizontalAlign
from edgar_sec.engine.tables.ascii_html.spans import (
    build_span_matrix,
    distribute_multi_row_span_lines,
    extract_source_table,
    repair_header_band_spans,
)

SPAN_HTML = """
<table style="width: 100%;">
  <tr>
    <th colspan="2">Consolidated Statement</th>
    <th>Notes</th>
  </tr>
  <tr>
    <td>Revenues</td>
    <td><table><tr><td>Nested Inside</td></tr></table></td>
    <td>1</td>
  </tr>
</table>
"""


def _source(html: str, index: int = 0):
    node = parse_html(html).css_first("table")
    assert node is not None
    return extract_source_table(node, table_index=index)


def test_colspan_occupies_several_matrix_positions_under_one_owner() -> None:
    source, _ = _source(SPAN_HTML)
    matrix, spans = build_span_matrix(source)
    assert len(matrix) == 2
    assert len(matrix[0]) == 3
    assert matrix[0][0] is matrix[0][1]
    assert matrix[0][2] is not matrix[0][0]
    assert len(spans) == 1
    assert (spans[0].start_col, spans[0].end_col) == (0, 1)


def test_nested_tables_are_isolated_and_indexed_from_the_containing_cell() -> None:
    source, nested = _source(SPAN_HTML)
    assert len(nested) == 1
    assert nested[0].parent_table_index == 0
    holder = [
        cell for row in source.rows for cell in row if cell.is_nested_table_holder
    ]
    assert len(holder) == 1
    assert holder[0].nested_table_index == 1


def test_a_rowspan_owner_appears_in_every_row_it_covers() -> None:
    source, _ = _source(
        "<table><tr><td rowspan='2'>Cost</td><td>400</td></tr>"
        "<tr><td>350</td></tr></table>"
    )
    matrix, spans = build_span_matrix(source)
    assert matrix[0][0] is matrix[1][0]
    assert len(spans) == 1
    assert (spans[0].start_row, spans[0].end_row) == (0, 1)


def test_the_matrix_is_padded_to_a_uniform_width() -> None:
    source, _ = _source(
        "<table><tr><td>a</td><td>b</td><td>c</td></tr><tr><td>d</td></tr></table>"
    )
    matrix, _ = build_span_matrix(source)
    assert all(len(row) == 3 for row in matrix)


def test_an_empty_source_table_produces_no_matrix_and_no_spans() -> None:
    assert build_span_matrix(_source("<table></table>")[0]) == ([], [])


def test_rows_hidden_by_style_are_dropped_from_the_source() -> None:
    source, _ = _source(
        '<table><tr><td>a</td></tr><tr style="display:none"><td>b</td></tr></table>'
    )
    assert len(source.rows) == 1


def test_hidden_cells_are_dropped_and_the_rest_keep_their_order() -> None:
    source, _ = _source(
        '<table><tr><td>a</td><td style="display:none">b</td><td>c</td></tr></table>'
    )
    assert [cell.text for cell in source.rows[0]] == ["a", "c"]


def test_non_breaking_space_prefixes_become_a_discrete_indent() -> None:
    source, _ = _source(
        "<table><tr><td>&nbsp;&nbsp;&nbsp;&nbsp;Indented</td></tr></table>"
    )
    cell = source.rows[0][0]
    assert cell.indent_spaces == 4
    assert cell.text.startswith("    ")


def test_numeric_and_center_aligned_cells_suppress_their_indent() -> None:
    numeric, _ = _source("<table><tr><td>&nbsp;&nbsp;1,200</td></tr></table>")
    assert numeric.rows[0][0].indent_spaces == 0
    centered, _ = _source(
        '<table><tr><td align="center">&nbsp;&nbsp;Value</td></tr></table>'
    )
    assert centered.rows[0][0].indent_spaces == 0


def test_preformatted_white_space_keeps_its_newlines() -> None:
    source, _ = _source(
        '<table><tr><td style="white-space:pre">one\ntwo</td></tr></table>'
    )
    assert "\n" in source.rows[0][0].text


def test_header_band_repair_extends_a_label_over_its_repeated_subheaders() -> None:
    source, _ = _source(
        "<table>"
        "<tr><td colspan='2'>Year Ended</td><td colspan='2'>Year Ended</td></tr>"
        "<tr><td>2024</td><td>Q1</td><td>2025</td><td>Q1</td></tr>"
        "</table>"
    )
    matrix, _ = build_span_matrix(source)
    repair_header_band_spans(matrix)
    assert matrix[0][0] is matrix[0][1]
    assert matrix[0][2] is matrix[0][3]
    assert matrix[0][0] is not matrix[0][2]


def test_header_band_repair_never_touches_a_row_carrying_financial_data() -> None:
    source, _ = _source(
        "<table>"
        "<tr><td colspan='2'>$1,000</td><td colspan='2'>$2,000</td></tr>"
        "<tr><td>2024</td><td>Q1</td><td>2025</td><td>Q1</td></tr>"
        "</table>"
    )
    matrix, _ = build_span_matrix(source)
    before = [id(cell) for cell in matrix[0]]
    repair_header_band_spans(matrix)
    assert [id(cell) for cell in matrix[0]] == before


def test_multi_row_span_lines_are_split_across_the_rows_they_cover() -> None:
    from edgar_sec.engine.tables.ascii_html.blocks import RenderBlock
    from edgar_sec.engine.tables.ascii_html.model import (
        SourceCell,
    )

    spanning = SourceCell(
        row_index=0, source_col_index=0, tag="td", text="one two three", rowspan=3
    )
    blocks = [
        [RenderBlock(spanning, [0], 30, HorizontalAlign.LEFT, "one two three")],
        [RenderBlock(spanning, [0], 30, HorizontalAlign.LEFT, "")],
        [RenderBlock(spanning, [0], 30, HorizontalAlign.LEFT, "")],
    ]
    lines = [[[]], [[]], [[]]]
    distribute_multi_row_span_lines(blocks, lines)
    assert lines[0][0] == ["one two three"]
    assert lines[1][0] == []
    assert lines[2][0] == []


def test_a_multi_line_span_body_is_sliced_across_the_rows_it_covers() -> None:
    from edgar_sec.engine.tables.ascii_html.blocks import RenderBlock
    from edgar_sec.engine.tables.ascii_html.model import (
        SourceCell,
    )

    spanning = SourceCell(
        row_index=0,
        source_col_index=0,
        tag="td",
        text="alpha bravo charlie delta echo foxtrot",
        rowspan=2,
    )
    blocks = [
        [RenderBlock(spanning, [0], 12, HorizontalAlign.LEFT, spanning.text)],
        [RenderBlock(spanning, [0], 12, HorizontalAlign.LEFT, "")],
    ]
    lines = [[[]], [[]]]
    distribute_multi_row_span_lines(blocks, lines)
    assert lines[0][0]
    assert lines[1][0]
    assert lines[0][0] != lines[1][0]


def test_a_span_that_owns_a_single_row_is_left_alone() -> None:
    from edgar_sec.engine.tables.ascii_html.blocks import RenderBlock
    from edgar_sec.engine.tables.ascii_html.model import SourceCell

    single = SourceCell(row_index=0, source_col_index=0, tag="td", text="x")
    blocks = [[RenderBlock(single, [0], 4, HorizontalAlign.LEFT, "x")]]
    lines = [[["x"]]]
    distribute_multi_row_span_lines(blocks, lines)
    assert lines[0][0] == ["x"]
