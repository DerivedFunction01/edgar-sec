"""Coordinate estimation and the interval math behind resolved columns."""

from __future__ import annotations

import pytest

from edgar_sec.engine.document.html.tree import parse_html
from edgar_sec.engine.tables.ascii_html.geometry import estimate_table_geometry
from edgar_sec.engine.tables.ascii_html.model import HorizontalAlign, SourceTable
from edgar_sec.engine.tables.ascii_html.spans import (
    build_span_matrix,
    extract_source_table,
)

SIZED_HTML = """
<table>
  <tr>
    <th style="width: 200px;">Period</th>
    <th style="width: 100px;">Shares</th>
    <th style="width: 100px;">Price</th>
  </tr>
  <tr>
    <td>Q1 2024</td><td align="right">1,000</td><td align="right">$25.50</td>
  </tr>
</table>
"""


def _geometry(html: str):
    node = parse_html(html).css_first("table")
    assert node is not None
    source, _ = extract_source_table(node)
    matrix, spans = build_span_matrix(source)
    return source, matrix, estimate_table_geometry(source, matrix, spans)


def test_a_declared_width_produces_a_box_at_least_that_wide() -> None:
    _source, _matrix, boxes = _geometry(SIZED_HTML)
    assert len(boxes) == 2
    assert len(boxes[0]) == 3
    assert boxes[0][0] is not None
    assert boxes[0][0].width >= 200.0


def test_declared_widths_place_columns_side_by_side_without_overlap() -> None:
    _source, _matrix, boxes = _geometry(SIZED_HTML)
    first, second, third = (boxes[1][c] for c in range(3))
    assert first.left == 0.0
    assert first.right <= second.left
    assert second.right <= third.left
    assert third.right > 0.0


def test_a_spanning_cell_occupies_its_whole_region_with_one_box() -> None:
    _source, _matrix, boxes = _geometry(
        "<table><tr><td colspan='2'>total</td><td>1</td></tr>"
        "<tr><td>a</td><td>b</td><td>2</td></tr></table>"
    )
    assert boxes[0][0] is boxes[0][1]
    assert boxes[0][0] is not boxes[0][2]


def test_a_declared_dimension_confidence_is_higher_than_an_inferred_one() -> None:
    _source, _matrix, boxes = _geometry(SIZED_HTML)
    sized = boxes[0][0]
    assert sized is not None
    assert sized.confidence == 1.0


def test_an_inferred_width_uses_about_eight_pixels_per_character() -> None:
    _source, _matrix, boxes = _geometry("<table><tr><td>abcd</td></tr></table>")
    box = boxes[0][0]
    assert box is not None
    assert box.confidence == pytest.approx(0.8)
    assert box.width >= 4 * 8.0


def test_column_zero_is_the_geometry_origin_and_rows_stack_downward() -> None:
    _source, _matrix, boxes = _geometry(SIZED_HTML)
    assert boxes[0][0] is not None
    assert boxes[0][0].top == 0.0
    assert boxes[1][0] is not None
    assert boxes[1][0].top == pytest.approx(boxes[0][0].bottom)


def test_an_empty_grid_yields_no_boxes() -> None:
    assert estimate_table_geometry(SourceTable(table_index=0), [], []) == []


def test_geometry_agrees_with_the_resolved_column_alignments() -> None:
    from edgar_sec.engine.tables.ascii_html.columns import resolve_columns

    _source, matrix, boxes = _geometry(SIZED_HTML)
    _active, alignments, _spacers = resolve_columns(matrix, boxes)
    assert alignments[0] is HorizontalAlign.LEFT
    assert len(alignments) == 3
