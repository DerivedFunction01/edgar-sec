"""Confidence scoring and the veto conditions that describe a lost grid."""

from __future__ import annotations

import pytest

from edgar_sec.engine.document.html.tree import parse_html
from edgar_sec.engine.tables.ascii_html.converter import convert_html_table
from edgar_sec.engine.tables.ascii_html.diagnostics import evaluate_table_confidence
from edgar_sec.engine.tables.ascii_html.model import (
    HorizontalAlign,
    ResolvedGrid,
    SourceTable,
    SpanGroup,
    TextLayoutDiagnostic,
)
from edgar_sec.engine.tables.ascii_html.spans import extract_source_table

EMPTY_GRID = ResolvedGrid(rows=(), column_alignments=(), column_widths=())
pytest_approx = pytest.approx


def _source(html: str) -> SourceTable:
    node = parse_html(html).css_first("table")
    assert node is not None
    source, _ = extract_source_table(node)
    return source


def _grid(rows: tuple[tuple[str, ...], ...], widths: tuple[int, ...]):
    return ResolvedGrid(
        rows=rows,
        column_alignments=tuple(HorizontalAlign.LEFT for _ in widths),
        column_widths=widths,
    )


def test_an_empty_grid_scores_zero_with_a_stated_reason() -> None:
    confidence, reasons = evaluate_table_confidence(
        SourceTable(table_index=0), EMPTY_GRID, []
    )
    assert confidence == 0.0
    assert reasons == ["Empty table or zero resolved columns"]


def test_a_grid_with_no_column_widths_is_vetoed() -> None:
    confidence, reasons = evaluate_table_confidence(
        SourceTable(table_index=0), _grid((("a",),), ()), []
    )
    assert confidence == 0.0
    assert "Empty table or zero resolved columns" in reasons


def test_a_clean_grid_scores_one_with_no_reasons() -> None:
    source = _source("<table><tr><td>a</td><td>1</td></tr></table>")
    grid = _grid((("a", "1"),), (4, 4))
    confidence, reasons = evaluate_table_confidence(source, grid, [])
    assert confidence == 1.0
    assert reasons == []


def test_a_multi_cell_source_collapsed_into_one_column_is_vetoed() -> None:
    source = _source(
        "<table><tr><td>a</td><td>b</td><td>c</td></tr>"
        "<tr><td>d</td><td>e</td><td>f</td></tr>"
        "<tr><td>g</td><td>h</td><td>i</td></tr></table>"
    )
    confidence, reasons = evaluate_table_confidence(source, _grid((("a",),), (4,)), [])
    assert confidence == 0.6
    assert "Multi-cell source table collapsed into single column" in reasons


def test_a_short_source_collapsed_to_one_column_is_tolerated() -> None:
    source = _source(
        "<table><tr><td>a</td><td>b</td></tr><tr><td>c</td><td>d</td></tr></table>"
    )
    confidence, reasons = evaluate_table_confidence(source, _grid((("a",),), (4,)), [])
    assert confidence == 1.0
    assert reasons == []


def test_clipped_cells_lower_confidence_and_are_reported() -> None:
    source = _source("<table><tr><td>a</td><td>b</td></tr></table>")
    grid = ResolvedGrid(
        rows=(("a", "b"),),
        column_alignments=(HorizontalAlign.LEFT, HorizontalAlign.LEFT),
        column_widths=(4, 4),
        diagnostics=(
            TextLayoutDiagnostic(
                row=0, column=0, original_length=40, rendered_lines=10, clipped=True
            ),
        ),
    )
    confidence, reasons = evaluate_table_confidence(source, grid, [])
    assert confidence == pytest_approx(0.95)
    assert reasons == ["1 cells clipped by width budget"]


def test_span_domination_lowers_confidence_and_is_reported() -> None:
    source = _source("<table><tr><td>a</td><td>b</td></tr></table>")
    cell = source.rows[0][0]
    span = SpanGroup(start_row=0, end_row=0, start_col=0, end_col=0, source_cell=cell)
    confidence, reasons = evaluate_table_confidence(
        source, _grid((("a",),), (4,)), [span]
    )
    assert confidence == pytest_approx(0.8)
    assert "Excessive span complexity across table grid" in reasons


def test_a_sparse_span_set_does_not_lower_confidence() -> None:
    source = _source("<table><tr><td>a</td><td>b</td></tr></table>")
    cell = source.rows[0][0]
    span = SpanGroup(start_row=0, end_row=0, start_col=0, end_col=1, source_cell=cell)
    confidence, reasons = evaluate_table_confidence(
        source, _grid((("a", "b"),), (4, 4)), [span]
    )
    assert confidence == 1.0
    assert reasons == []


def test_confidence_is_clamped_to_the_unit_interval() -> None:
    source = _source("<table><tr><td>a</td></tr></table>")
    grid = ResolvedGrid(
        rows=(("a",),),
        column_alignments=(HorizontalAlign.LEFT,),
        column_widths=(4,),
        diagnostics=tuple(
            TextLayoutDiagnostic(
                row=0, column=0, original_length=1, rendered_lines=1, clipped=True
            )
            for _ in range(50)
        ),
    )
    confidence, _reasons = evaluate_table_confidence(source, grid, [])
    assert 0.0 <= confidence <= 1.0


def test_a_fully_rendered_table_reports_high_confidence() -> None:
    result = convert_html_table(
        "<table><tr><th>Line Item</th><th>Amount</th></tr>"
        "<tr><td>Revenue</td><td>1,000</td></tr></table>"
    )
    assert result.confidence >= 0.8
