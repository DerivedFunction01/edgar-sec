"""Geometry model types: the fields a caller reads instead of re-parsing text."""

from __future__ import annotations

import pytest

from edgar_sec.engine.tables.ascii_html.converter import convert_html_table
from edgar_sec.engine.tables.ascii_html.model import (
    DEFAULT_RENDER_BUDGET,
    BorderSegment,
    BorderStyle,
    CellBox,
    CellStyle,
    HorizontalAlign,
    RenderBudget,
    ResolvedGrid,
    SourceCell,
    SourceTable,
    SpanGroup,
    TableGeometry,
    TableRenderResult,
    TextLayoutDiagnostic,
    VerticalAlign,
)

HTML = (
    "<table><tr><th>Metric</th><th>Value</th></tr>"
    "<tr><td>Sales</td><td>5</td></tr></table>"
)


def _geometry() -> TableGeometry:
    return TableGeometry(table_index=3, render_result=convert_html_table(HTML))


def test_alignment_enums_are_strings_so_they_survive_a_json_round_trip() -> None:
    assert HorizontalAlign.RIGHT == "right"
    assert VerticalAlign.BOTTOM == "bottom"
    assert BorderStyle.DOUBLE == "double"


def test_cell_box_never_reports_a_negative_extent() -> None:
    box = CellBox(left=10.0, right=4.0, top=5.0, bottom=5.0, confidence=1.0)
    assert box.width == 0.0
    assert box.height == 0.0


def test_cell_style_defaults_are_neutral() -> None:
    style = CellStyle()
    assert style.width is None
    assert style.text_align is HorizontalAlign.AUTO
    assert style.border_bottom_style is BorderStyle.NONE
    assert style.is_hidden is False


def test_render_budget_defaults_bound_the_table_width() -> None:
    assert DEFAULT_RENDER_BUDGET.max_table_width == 180
    assert DEFAULT_RENDER_BUDGET.column_spacing == 2
    assert isinstance(DEFAULT_RENDER_BUDGET, RenderBudget)


def test_table_geometry_projects_its_render_result() -> None:
    geometry = _geometry()
    assert geometry.table_index == 3
    assert geometry.rows == (("Metric", "Value"), ("Sales", "5"))
    assert len(geometry.column_widths) == 2
    assert isinstance(geometry.confidence, float)
    assert isinstance(geometry.diagnostics, tuple)
    assert geometry.is_fallback_to_legacy is False
    assert geometry.resolved_grid is geometry.render_result.resolved_grid


def test_span_group_records_the_region_it_owns() -> None:
    cell = SourceCell(row_index=0, source_col_index=0, tag="td", text="x", colspan=2)
    group = SpanGroup(start_row=0, end_row=1, start_col=0, end_col=1, source_cell=cell)
    assert group.source_cell is cell
    assert (group.start_col, group.end_col) == (0, 1)


def test_border_segment_defaults_to_a_solid_one_point_rule() -> None:
    segment = BorderSegment(row=0, start_column=0, end_column=2, edge="bottom")
    assert segment.style is BorderStyle.SOLID
    assert segment.width == 1.0
    assert segment.confidence == 1.0


def test_resolved_grid_carries_its_own_diagnostics() -> None:
    grid = ResolvedGrid(
        rows=(("a",),),
        column_alignments=(HorizontalAlign.LEFT,),
        column_widths=(1,),
        diagnostics=(
            TextLayoutDiagnostic(
                row=0,
                column=0,
                original_length=9,
                rendered_lines=9,
                forced_wrap=True,
            ),
        ),
    )
    assert grid.diagnostics[0].forced_wrap is True
    assert grid.diagnostics[0].clipped is False


def test_empty_source_table_has_no_rows() -> None:
    assert SourceTable(table_index=0).rows == ()


def test_table_render_result_is_immutable() -> None:
    result = TableRenderResult(
        ascii_text="",
        resolved_grid=ResolvedGrid(rows=(), column_alignments=(), column_widths=()),
        confidence=0.0,
    )
    with pytest.raises(AttributeError):
        result.ascii_text = "x"  # type: ignore[misc]
