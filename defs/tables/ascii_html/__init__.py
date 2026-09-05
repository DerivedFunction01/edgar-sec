"""Geometry-first ASCII table renderer for SEC HTML tables."""

from __future__ import annotations

from defs.tables.ascii_html.model import (
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
    TableRenderResult,
    TextLayoutDiagnostic,
    VerticalAlign,
)
from defs.tables.ascii_html.renderer import render_grid_to_ascii, render_source_table
from defs.tables.ascii_html.spans import (
    build_span_matrix,
    extract_source_table,
)
from defs.text.html import FastHtmlNode, parse_html


def convert_html_table(
    table_html: str | bytes | FastHtmlNode,
    *,
    table_index: int = 0,
    budget: RenderBudget = DEFAULT_RENDER_BUDGET,
) -> TableRenderResult:
    """Convert an HTML <table> string, bytes, or FastHtmlNode into canonical ASCII table format."""
    if isinstance(table_html, FastHtmlNode):
        table_node = table_html
    else:
        tree = parse_html(table_html)
        node = tree.css_first("table")
        if node is None:
            empty_grid = ResolvedGrid(
                rows=(),
                column_alignments=(),
                column_widths=(),
                confidence=0.0,
                veto_reasons=("No <table> tag found",),
            )
            return TableRenderResult(
                ascii_text="",
                resolved_grid=empty_grid,
                confidence=0.0,
                diagnostics=("No <table> tag found",),
            )
        table_node = node

    return render_source_table(table_node, table_index=table_index, budget=budget)


def convert_html_tables_to_ascii(
    html_content: str,
    *,
    budget: RenderBudget = DEFAULT_RENDER_BUDGET,
) -> str:
    """Document-level facade: converts all visual HTML tables in a document to ASCII tables."""
    tree = parse_html(html_content)
    tables = tree.css("table")
    if not tables:
        return tree.root.text(separator="\n") if tree.root else html_content

    for idx, tbl in enumerate(tables):
        if tbl.find_parent("table") is not None:
            continue
        res = render_source_table(tbl, table_index=idx, budget=budget)
        if res.ascii_text:
            tbl.raw_node.replace_with(f"\n{res.ascii_text}\n")

    root = tree.root
    return root.text(separator="\n") if root else html_content


__all__ = [
    "BorderSegment",
    "BorderStyle",
    "CellBox",
    "CellStyle",
    "HorizontalAlign",
    "RenderBudget",
    "ResolvedGrid",
    "SourceCell",
    "SourceTable",
    "SpanGroup",
    "TableRenderResult",
    "TextLayoutDiagnostic",
    "VerticalAlign",
    "build_span_matrix",
    "convert_html_table",
    "convert_html_tables_to_ascii",
    "extract_source_table",
    "render_grid_to_ascii",
    "render_source_table",
]
