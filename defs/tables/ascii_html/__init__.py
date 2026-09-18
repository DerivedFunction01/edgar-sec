"""Geometry-first ASCII table renderer for SEC HTML tables."""

from __future__ import annotations

import re

from defs.tables.ascii_html.continuation import (
    ContinuationDecision,
    detect_table_continuation,
    fuse_source_tables,
)
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
    TableGeometry,
    TableRenderResult,
    TextLayoutDiagnostic,
    VerticalAlign,
)
from defs.tables.ascii_html.quick_grid import quick_extract_table_grid
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
    """Convert visual HTML tables to ASCII, optionally preserving markup."""
    rendered, _ = convert_html_tables_to_ascii_with_metadata(
        html_content,
        budget=budget,
        convert_to_text=convert_to_text,
    )
    return rendered


def convert_html_tables_to_ascii_with_metadata(
    html_content: str,
    *,
    budget: RenderBudget = DEFAULT_RENDER_BUDGET,
    convert_to_text: bool = True,
    early_unwrap_false_tables: bool = False,
) -> tuple[str, tuple[TableGeometry, ...]]:
    """Convert HTML tables to ASCII, returning text and per-table geometry metadata.

    Identical to :func:`convert_html_tables_to_ascii` except that a
    :class:`TableGeometry` instance is retained for every table that
    produces rendered output. Wholly-empty tables that are decomposed
    are omitted from the metadata, matching the string output behavior.
    """
    tree = parse_html(html_content)
    tables = tree.css("table")
    if not tables:
        if tree.root is None:
            return html_content, ()
        return (
            tree.root.text(separator="\n") if convert_to_text else str(tree),
            (),
        )

    top_tables = [tbl for tbl in tables if tbl.find_parent("table") is None]
    if not top_tables:
        return (
            tree.root.text(separator="\n")
            if convert_to_text and tree.root
            else str(tree),
            (),
        )

    # O5: per-node cache for is_wholly_empty_table (called up to 3x per table)
    _empty_cache: dict[int, bool] = {}

    def _is_empty(tbl: FastHtmlNode) -> bool:
        k = id(tbl.raw_node)
        v = _empty_cache.get(k)
        if v is None:
            v = not tbl.text(strip=True)
            _empty_cache[k] = v
        return v

    # O1: Pre-filter obvious false tables using fast DOM scan (no CSS parsing).
    # Tables with colspan/rowspan or nested <table> elements return None and
    # fall through to the full extract_source_table path.
    is_false_list: list[bool] = [False] * len(top_tables)
    unwrapped_texts: list[str] = [""] * len(top_tables)

    if early_unwrap_false_tables:
        from defs.tables.false_tables import is_false_grid, unwrap_grid

        for i, tbl in enumerate(top_tables):
            quick = quick_extract_table_grid(tbl)
            if quick is not None and quick and is_false_grid(quick):
                is_false_list[i] = True
                unwrapped_texts[i] = unwrap_grid(quick)

    # Build source_tables, skipping full extraction for pre-classified false tables.
    # None sentinels are always guarded by is_false_list[i] in downstream loops.
    source_tables: list[SourceTable | None] = []
    for i, tbl in enumerate(top_tables):
        if is_false_list[i]:
            source_tables.append(None)
        else:
            source_tables.append(extract_source_table(tbl, table_index=i)[0])

    if early_unwrap_false_tables:
        for i, source in enumerate(source_tables):
            if is_false_list[i]:
                continue  # already classified by quick pre-filter
            if source is None or not source.rows or _is_empty(top_tables[i]):
                continue
            matrix, _ = build_span_matrix(source)
            grid_rows = tuple(
                tuple(cell.text if cell else "" for cell in row) for row in matrix
            )
            if is_false_grid(grid_rows):
                is_false_list[i] = True
                unwrapped_texts[i] = unwrap_grid(grid_rows)

        # Footnote lookahead for tables immediately preceding a retained table
        for i in range(len(top_tables)):
            if is_false_list[i] or not (
                source_tables[i] is not None and source_tables[i].rows
            ):
                continue
            if (
                i + 1 < len(top_tables)
                and not is_false_list[i + 1]
                and source_tables[i + 1] is not None
                and source_tables[i + 1].rows
            ):
                matrix, _ = build_span_matrix(source_tables[i])
                grid_rows = tuple(
                    tuple(cell.text if cell else "" for cell in row) for row in matrix
                )
                if is_false_grid(grid_rows, allow_footnote_context=True):
                    is_false_list[i] = True
                    unwrapped_texts[i] = unwrap_grid(grid_rows)

    clusters: list[list[int]] = []
    fused_sources: list[SourceTable] = []

    for i, tbl in enumerate(top_tables):
        if is_false_list[i]:
            tbl.raw_node.replace_with(f"\n{unwrapped_texts[i]}\n")
            continue

        if _is_empty(tbl):
            if not convert_to_text:
                tbl.decompose()
            continue

        source = source_tables[i]  # not None: only None when is_false_list[i]
        assert source is not None
        if not source.rows:
            clusters.append([i])
            fused_sources.append(source)
            continue
        if (
            clusters
            and fused_sources[-1].rows
            and len(fused_sources[-1].rows[0]) == len(source.rows[0])
        ):
            prev_idx = clusters[-1][-1]
            prev_tbl = top_tables[prev_idx]
            prev_source = fused_sources[-1]

            intervening_text_pieces = []
            curr = prev_tbl.raw_node.next
            too_far = False
            total_chars = 0
            while curr and curr != tbl.raw_node:
                tag = curr.tag
                if tag == "table":
                    too_far = True
                    break
                t = curr.text(deep=True) or ""
                if t.strip():
                    total_chars += len(t)
                    if total_chars > 100:
                        too_far = True
                        break
                    intervening_text_pieces.append(t)
                curr = curr.next

            if curr != tbl.raw_node:
                too_far = True

            if not too_far:
                intervening_text = " ".join(intervening_text_pieces)
                decision = detect_table_continuation(
                    prev_source, source, intervening_html=intervening_text
                )
                if decision.is_continuation:
                    clusters[-1].append(i)
                    fused_sources[-1] = fuse_source_tables(
                        prev_source, source, decision.header_rows_to_drop
                    )
                    continue
        clusters.append([i])
        fused_sources.append(source)

    rendered_tables: list[tuple[str, str]] = []
    geometries: list[TableGeometry] = []
    has_token_prefix = "__SEC_RENDERED_TABLE_" in html_content

    for cluster_idx, cluster in enumerate(clusters):
        primary_idx = cluster[0]
        primary_tbl = top_tables[primary_idx]
        fused_source = fused_sources[cluster_idx]

        res = render_source_table(
            fused_source,
            table_index=len(geometries),
            budget=budget,
        )

        for sec_idx in cluster[1:]:
            top_tables[sec_idx].raw_node.replace_with("")

        if res.ascii_text:
            if convert_to_text:
                primary_tbl.raw_node.replace_with(f"\n{res.ascii_text}\n")
            else:
                token = f"__SEC_RENDERED_TABLE_{len(rendered_tables)}__"
                if has_token_prefix:
                    while token in html_content:
                        token += "_"
                rendered_tables.append((token, f"\n{res.ascii_text}\n"))
                primary_tbl.raw_node.replace_with(token)
            geometries.append(
                TableGeometry(
                    table_index=len(geometries),
                    render_result=res,
                )
            )
        elif not convert_to_text:
            if _is_empty(primary_tbl):
                primary_tbl.decompose()
                continue
            token = f"__SEC_RENDERED_TABLE_{len(rendered_tables)}__"
            if has_token_prefix:
                while token in html_content:
                    token += "_"
            raw_html = primary_tbl.raw_node.html or ""
            match = _RE_TABLE_WRAPPER.fullmatch(raw_html)
            inner_html = match.group("body") if match else raw_html
            rendered_tables.append((token, f"\n<TABLE>{inner_html}</TABLE>\n"))
            primary_tbl.raw_node.replace_with(token)
            geometries.append(
                TableGeometry(
                    table_index=len(geometries),
                    render_result=res,
                )
            )

    root = tree.root
    if root is None:
        return html_content, tuple(geometries)
    rendered = root.text(separator="\n") if convert_to_text else str(tree)
    if rendered_tables:
        token_map = dict(rendered_tables)
        token_re = re.compile("|".join(re.escape(k) for k in token_map))
        seen_tokens: set[str] = set()

        def _replace_token(match: re.Match[str]) -> str:
            t = match.group(0)
            seen_tokens.add(t)
            return token_map[t]

        rendered = token_re.sub(_replace_token, rendered)
        if len(seen_tokens) != len(rendered_tables):
            for token, _ in rendered_tables:
                if token not in seen_tokens:
                    raise ValueError(f"rendered table token missing: {token!r}")
    return rendered, tuple(geometries)


__all__ = [
    "BorderSegment",
    "BorderStyle",
    "CellBox",
    "CellStyle",
    "ContinuationDecision",
    "HorizontalAlign",
    "RenderBudget",
    "ResolvedGrid",
    "SourceCell",
    "SourceTable",
    "SpanGroup",
    "TableGeometry",
    "TableRenderResult",
    "TextLayoutDiagnostic",
    "VerticalAlign",
    "build_span_matrix",
    "convert_html_table",
    "convert_html_tables_to_ascii",
    "convert_html_tables_to_ascii_with_metadata",
    "detect_table_continuation",
    "extract_source_table",
    "fuse_source_tables",
    "render_grid_to_ascii",
    "render_source_table",
]
