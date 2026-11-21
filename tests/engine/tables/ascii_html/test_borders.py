"""Border segment extraction and the multi-signal header boundary score."""

from __future__ import annotations

from edgar_sec.engine.document.html.tree import parse_html
from edgar_sec.engine.tables.ascii_html.borders import (
    extract_border_segments,
    score_header_boundary,
)
from edgar_sec.engine.tables.ascii_html.model import BorderStyle, SourceCell
from edgar_sec.engine.tables.ascii_html.spans import (
    build_span_matrix,
    extract_source_table,
)

DOUBLE_BORDER_HTML = """
<table>
  <tr>
    <th style="border-bottom: 3px double #1f4e79;"><b>Year</b></th>
    <th style="border-bottom: 3px double #1f4e79;"><b>Amount</b></th>
  </tr>
  <tr>
    <td style="border-bottom: 1px solid #d3d3d3;">2024</td>
    <td style="border-bottom: 1px solid #d3d3d3;">$500</td>
  </tr>
  <tr><td>2023</td><td>$450</td></tr>
</table>
"""


def _matrix(html: str):
    node = parse_html(html).css_first("table")
    assert node is not None
    source, _ = extract_source_table(node)
    return build_span_matrix(source)


def _cell(text: str, **style: object) -> SourceCell:
    from edgar_sec.engine.document.html.tree import parse_html as _parse
    from edgar_sec.engine.tables.ascii_html.cell import parse_style_and_attributes

    node = _parse(f"<table><tr><td style='x:1'>{text}</td></tr></table>").css_first(
        "td"
    )
    assert node is not None
    return SourceCell(
        row_index=0,
        source_col_index=0,
        tag="td",
        text=text,
        style=parse_style_and_attributes(node),
        **style,  # type: ignore[arg-type]
    )


def test_a_cell_border_becomes_one_segment_per_edge() -> None:
    matrix, _ = _matrix(
        '<table><tr><td style="border-bottom:1px solid #000">a</td></tr></table>'
    )
    segments = extract_border_segments(matrix, [0])
    assert len(segments) == 1
    assert segments[0].edge == "bottom"
    assert segments[0].style is BorderStyle.SOLID
    assert segments[0].color == "#000"


def test_contiguous_segments_on_one_row_and_style_merge_into_one_run() -> None:
    matrix, _ = _matrix(
        "<table><tr>"
        '<td style="border-bottom:1px solid #000">a</td>'
        '<td style="border-bottom:1px solid #000">b</td>'
        '<td style="border-bottom:1px solid #000">c</td>'
        "</tr></table>"
    )
    segments = extract_border_segments(matrix, [0, 1, 2])
    assert len(segments) == 1
    assert (segments[0].start_column, segments[0].end_column) == (0, 2)


def test_a_differently_styled_neighbour_does_not_merge_into_the_run() -> None:
    matrix, _ = _matrix(
        "<table><tr>"
        '<td style="border-bottom:1px solid #000">a</td>'
        '<td style="border-bottom:2px solid #111">b</td>'
        "</tr></table>"
    )
    assert len(extract_border_segments(matrix, [0, 1])) == 2


def test_a_table_with_no_cells_produces_no_segments() -> None:
    assert extract_border_segments([], []) == []
    assert extract_border_segments([[None]], [0]) == []


def test_a_double_border_and_a_colour_transition_score_one_header_row() -> None:
    matrix, _ = _matrix(DOUBLE_BORDER_HTML)
    active = [0, 1]
    segments = extract_border_segments(matrix, active)
    header_rows, divider_style = score_header_boundary(matrix, active, segments)
    assert header_rows == 1
    assert divider_style is BorderStyle.DOUBLE


def test_a_table_with_no_header_evidence_scores_zero_header_rows() -> None:
    matrix, _ = _matrix("<table><tr><td>a</td></tr><tr><td>b</td></tr></table>")
    header_rows, divider_style = score_header_boundary(matrix, [0], [])
    assert header_rows == 0
    assert divider_style is BorderStyle.SOLID


def test_a_single_row_table_cannot_have_a_header_boundary() -> None:
    matrix, _ = _matrix("<table><tr><th>a</th></tr></table>")
    assert score_header_boundary(matrix, [0], []) == (0, BorderStyle.SOLID)
    assert score_header_boundary([], [], []) == (0, BorderStyle.SOLID)


def test_a_candidate_header_row_carrying_amounts_is_never_accepted() -> None:
    matrix, _ = _matrix(
        "<table><tr><th>1,200</th></tr>"
        '<tr><td style="border-bottom:1px solid #000">2</td></tr>'
        "<tr><td>3</td></tr></table>"
    )
    header_rows, _ = score_header_boundary(
        matrix, [0], extract_border_segments(matrix, [0])
    )
    assert header_rows == 0


def test_a_four_digit_year_does_not_disqualify_a_header_row() -> None:
    matrix, _ = _matrix(
        "<table><tr><th>2024</th></tr>"
        '<tr><td style="border-bottom:1px solid #000">1,200</td></tr>'
        "<tr><td>2</td></tr></table>"
    )
    header_rows, _ = score_header_boundary(
        matrix, [0], extract_border_segments(matrix, [0])
    )
    assert header_rows == 1


def test_bold_cells_with_a_border_beat_bold_cells_without_one() -> None:
    bordered, _ = _matrix(
        '<table><tr><th style="border-bottom:1px solid #000"><b>Year</b></th></tr>'
        "<tr><td>2024</td></tr></table>"
    )
    assert (
        score_header_boundary(bordered, [0], extract_border_segments(bordered, [0]))[0]
        == 1
    )
    plain, _ = _matrix(
        "<table><tr><td><b>Year</b></td></tr><tr><td>2024</td></tr></table>"
    )
    assert (
        score_header_boundary(plain, [0], extract_border_segments(plain, [0]))[0] == 0
    )
