"""Geometry-first ASCII table renderer for SEC HTML tables."""

from __future__ import annotations

import re

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

_RE_TABLE_WRAPPER = re.compile(
    r"<table\b[^>]*>(?P<body>.*)</table\s*>\s*$",
    re.IGNORECASE | re.DOTALL,
)


def _is_wholly_empty_table(table_node: FastHtmlNode) -> bool:
    """Return True if the table has no visible text after whitespace normalization."""
    return not table_node.text(strip=True)


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
    convert_to_text: bool = True,
) -> str:
    """Convert visual HTML tables to ASCII, optionally preserving HTML markup."""
    tree = parse_html(html_content)
    tables = tree.css("table")
    if not tables:
        if tree.root is None:
            return html_content
        return tree.root.text(separator="\n") if convert_to_text else str(tree)

    rendered_tables: list[tuple[str, str]] = []
    for idx, tbl in enumerate(tables):
        if tbl.find_parent("table") is not None:
            continue
        res = render_source_table(tbl, table_index=idx, budget=budget)
        if res.ascii_text:
            if convert_to_text:
                tbl.raw_node.replace_with(f"\n{res.ascii_text}\n")
            else:
                token = f"__SEC_RENDERED_TABLE_{len(rendered_tables)}__"
                while token in html_content:
                    token += "_"
                rendered_tables.append((token, f"\n{res.ascii_text}\n"))
                tbl.raw_node.replace_with(token)
        elif not convert_to_text:
            if _is_wholly_empty_table(tbl):
                tbl.decompose()
                continue
            token = f"__SEC_RENDERED_TABLE_{len(rendered_tables)}__"
            while token in html_content:
                token += "_"
            raw_html = tbl.raw_node.html or ""
            match = _RE_TABLE_WRAPPER.fullmatch(raw_html)
            inner_html = match.group("body") if match else raw_html
            rendered_tables.append((token, f"\n<TABLE>{inner_html}</TABLE>\n"))
            tbl.raw_node.replace_with(token)

    root = tree.root
    if root is None:
        return html_content
    rendered = root.text(separator="\n") if convert_to_text else str(tree)
    for token, table in rendered_tables:
        if token not in rendered:
            raise ValueError(f"rendered table token missing: {token!r}")
        rendered = rendered.replace(token, table)
    return rendered


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
