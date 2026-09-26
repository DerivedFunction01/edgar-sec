"""Canonical ASCII table renderer for geometry-first HTML table presentation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from defs.tables.ascii_html.blocks import (
    align_terminal_numeric_headers,
    build_row_blocks,
    expand_numeric_blocks_to_header_bands,
    extract_raw_grids_and_spans,
    fuse_data_affix_blocks,
    fuse_empty_header_span_blocks,
    fuse_header_suffix_blocks,
)
from defs.tables.ascii_html.borders import (
    extract_border_segments,
    score_header_boundary,
)
from defs.tables.ascii_html.columns import (
    identify_affix_columns,
    is_affix_footnote_token,
    resolve_columns,
)
from defs.tables.ascii_html.diagnostics import evaluate_table_confidence
from defs.tables.ascii_html.dividers import (
    format_row_divider,
    format_top_divider,
    heal_divider_lines_from_templates,
    prune_unanchored_divider_fragments,
    repair_rendered_affix_columns,
)
from defs.tables.ascii_html.geometry import estimate_table_geometry
from defs.tables.ascii_html.model import (
    DEFAULT_RENDER_BUDGET,
    BorderStyle,
    HorizontalAlign,
    RenderBudget,
    ResolvedGrid,
    SourceTable,
    TableRenderResult,
    VerticalAlign,
)
from defs.tables.ascii_html.spans import (
    build_span_matrix,
    distribute_multi_row_span_lines,
    extract_source_table,
    repair_header_band_spans,
)
from defs.tables.ascii_html.text import (
    format_cell_line,
    normalize_grid_indents,
    wrap_cell_text,
)
from defs.tables.ascii_html.widths import compute_column_widths
from defs.tables.tokens import (
    is_numeric_cell,
    is_prefix_token,
    is_suffix_token,
)

if TYPE_CHECKING:
    from defs.text.html import FastHtmlNode


def _empty_render_result(reason: str) -> TableRenderResult:
    empty_grid = ResolvedGrid(
        rows=(),
        column_alignments=(),
        column_widths=(),
        confidence=0.0,
        veto_reasons=(reason,),
    )
    return TableRenderResult(
        ascii_text="",
        resolved_grid=empty_grid,
        confidence=0.0,
        diagnostics=(reason,),
    )


def render_source_table(
    table_input: FastHtmlNode | SourceTable,
    table_index: int = 0,
    budget: RenderBudget = DEFAULT_RENDER_BUDGET,
) -> TableRenderResult:
    """Render a single HTML <table> node or SourceTable into canonical ASCII table format."""
    # 1. Extract SourceTable and isolate nested tables
    if isinstance(table_input, SourceTable):
        source_table = table_input
    else:
        source_table, _ = extract_source_table(table_input, table_index=table_index)
    if not source_table.rows:
        return _empty_render_result("Empty source table")

    # 2. Build 2D span matrix and estimate coordinate geometry
    grid_matrix, span_groups = build_span_matrix(source_table)
    repair_header_band_spans(grid_matrix)
    # Strip leading and trailing empty spacer rows
    while grid_matrix and all(
        (cell is None or not cell.text.strip()) for cell in grid_matrix[0]
    ):
        grid_matrix.pop(0)
    while grid_matrix and all(
        (cell is None or not cell.text.strip()) for cell in grid_matrix[-1]
    ):
        grid_matrix.pop()

    if not grid_matrix:
        return _empty_render_result("Empty content table")

    box_matrix = estimate_table_geometry(source_table, grid_matrix, span_groups)

    # 3. Resolve active column bands and alignments
    active_cols, col_alignments, spacer_cols = resolve_columns(grid_matrix, box_matrix)
    if not active_cols:
        active_cols = list(range(len(grid_matrix[0])))
        col_alignments = [HorizontalAlign.LEFT] * len(active_cols)

    prefix_positions, suffix_positions = identify_affix_columns(
        grid_matrix, active_cols
    )

    # 4. Extract border segments and score header boundaries
    border_segments = extract_border_segments(grid_matrix, active_cols)
    header_row_count, header_divider_style = score_header_boundary(
        grid_matrix, active_cols, border_segments
    )

    # 5. Extract 2D raw text grid and span constraints for active columns
    raw_grid, single_col_grid, span_constraints = extract_raw_grids_and_spans(
        grid_matrix, active_cols
    )
    raw_grid, single_col_grid = normalize_grid_indents(raw_grid, single_col_grid)

    # Some filings place several caption rows before the actual column
    # subheaders, so the border-based header score can stop too early. Detect
    # only text-only rows immediately before the first numeric data row for the
    # narrow affix-header alignment adjustment.
    # Single pass: classify each row once as (is_empty, has_numeric)
    row_profiles: list[tuple[bool, bool]] = []
    for row in raw_grid:
        has_text = False
        has_num = False
        for cell in row:
            stripped = cell.strip()
            if stripped:
                has_text = True
                if is_numeric_cell(stripped):
                    has_num = True
                    break
        row_profiles.append((not has_text, has_num))

    terminal_header_rows: set[int] = set()
    next_non_empty_idx = -1
    for r in range(len(raw_grid) - 1, -1, -1):
        is_empty, has_num = row_profiles[r]
        if not is_empty:
            if (
                next_non_empty_idx != -1
                and not has_num
                and row_profiles[next_non_empty_idx][1]
            ):
                terminal_header_rows.add(r)
            next_non_empty_idx = r

    # 6. Compute column widths adhering to RenderBudget
    col_widths, layout_diags = compute_column_widths(
        raw_grid,
        col_alignments,
        span_constraints=span_constraints,
        prefix_positions=prefix_positions,
        budget=budget,
        single_col_rows=single_col_grid,
    )

    # 7. Construct ResolvedGrid & evaluate confidence / vetoes
    resolved_grid = ResolvedGrid(
        rows=tuple(tuple(r) for r in raw_grid),
        column_alignments=tuple(col_alignments),
        column_widths=tuple(col_widths),
        header_row_count=header_row_count,
        header_divider_style=header_divider_style,
        span_groups=tuple(span_groups),
        spacer_columns=tuple(spacer_cols),
        border_segments=tuple(border_segments),
        diagnostics=tuple(layout_diags),
    )
    confidence, veto_reasons = evaluate_table_confidence(
        source_table, resolved_grid, span_groups
    )

    # 8. Index border segments by row and column position
    row_top_borders: dict[int, dict[int, BorderStyle]] = {}
    row_bot_borders: dict[int, dict[int, BorderStyle]] = {}
    for seg in border_segments:
        target_dict = (
            row_top_borders.setdefault(seg.row, {})
            if seg.edge == "top"
            else row_bot_borders.setdefault(seg.row, {})
        )
        for c_pos in range(seg.start_column, seg.end_column + 1):
            if seg.style == BorderStyle.DOUBLE:
                target_dict[c_pos] = BorderStyle.DOUBLE
            elif c_pos not in target_dict:
                target_dict[c_pos] = seg.style

    # 9. Format ASCII text output
    num_cols = len(active_cols)
    non_empty_cols: set[int] = set()
    for row in raw_grid:
        for c, cell in enumerate(row):
            if c < num_cols and cell.strip():
                non_empty_cols.add(c)
    visible_col_indices: list[int] = [
        c for c in range(num_cols) if col_widths[c] > 0 and c in non_empty_cols
    ]
    if not visible_col_indices:
        visible_col_indices = list(range(num_cols))

    col_sep = " " * budget.column_spacing
    table_has_affix_token = False
    for source_row in grid_matrix:
        for cell in source_row:
            if cell is not None and (
                is_prefix_token(cell.text.strip()) or is_suffix_token(cell.text.strip())
            ):
                table_has_affix_token = True
                break
        if table_has_affix_token:
            break

    lines: list[str] = ["<TABLE>"]

    # Top border above table
    row_0_blocks = build_row_blocks(
        grid_matrix,
        0,
        active_cols,
        visible_col_indices,
        col_widths,
        col_alignments,
        raw_grid,
        budget,
    )
    top_div = format_top_divider(
        [(b.cell, b.span_cols, b.width) for b in row_0_blocks],
        row_top_borders,
        col_sep,
    )
    if top_div:
        lines.append(top_div)

    all_active_col_set = set(range(len(active_cols)))
    header_spans: list[set[int]] = []
    for h_r in range(header_row_count):
        h_blocks = build_row_blocks(
            grid_matrix,
            h_r,
            active_cols,
            visible_col_indices,
            col_widths,
            col_alignments,
            raw_grid,
            budget,
        )
        h_blocks = fuse_header_suffix_blocks(
            h_blocks,
            h_r,
            header_row_count,
            suffix_positions,
            budget,
        )
        for b in h_blocks:
            # Exclude full-table-width spans — these are caption/units rows that
            # should not collapse structural column gaps in body divider rows.
            if len(b.span_cols) > 1 and set(b.span_cols) != all_active_col_set:
                header_spans.append(set(b.span_cols))

    numeric_band_spans = list(header_spans)
    active_positions = {column: pos for pos, column in enumerate(active_cols)}
    for span in span_groups:
        text = span.source_cell.text.strip()
        if span.end_col - span.start_col + 1 != 3 or not text:
            continue
        mapped = [
            active_positions[column]
            for column in range(span.start_col, span.end_col + 1)
            if column in active_positions
        ]
        if len(mapped) == 3 and mapped == list(range(mapped[0], mapped[0] + 3)):
            candidate = set(mapped)
            if candidate not in numeric_band_spans:
                numeric_band_spans.append(candidate)

    # Build all row blocks
    all_row_blocks = []
    for r_idx in range(len(raw_grid)):
        blocks = build_row_blocks(
            grid_matrix,
            r_idx,
            active_cols,
            visible_col_indices,
            col_widths,
            col_alignments,
            raw_grid,
            budget,
        )
        blocks = fuse_header_suffix_blocks(
            blocks,
            r_idx,
            header_row_count,
            suffix_positions,
            budget,
        )
        blocks = fuse_data_affix_blocks(
            blocks,
            r_idx,
            header_row_count,
            prefix_positions,
            suffix_positions,
            budget,
        )
        blocks = expand_numeric_blocks_to_header_bands(
            blocks, numeric_band_spans, budget
        )
        protected_spans: set[tuple[int, ...]] = set()
        protected_spans.update(
            tuple(block.span_cols)
            for block in blocks
            if (
                len(block.span_cols) > 1
                and is_numeric_cell(block.text.strip())
                and not suffix_positions.isdisjoint(block.span_cols)
            )
        )
        if r_idx in terminal_header_rows:
            numeric_positions = {
                pos
                for pos, alignment in enumerate(col_alignments)
                if alignment == HorizontalAlign.RIGHT
            }
            affix_positions = prefix_positions | suffix_positions
            protected_spans = {
                tuple(block.span_cols)
                for block in blocks
                if (
                    block.text.strip()
                    and len(block.span_cols) <= 3
                    and not affix_positions.isdisjoint(block.span_cols)
                    and not numeric_positions.isdisjoint(block.span_cols)
                    and block.span_cols[-1] + 1 not in suffix_positions
                )
            }
        blocks = fuse_empty_header_span_blocks(
            blocks,
            r_idx,
            header_row_count,
            header_spans,
            budget,
            protected_spans=protected_spans,
        )
        blocks = align_terminal_numeric_headers(
            blocks,
            r_idx,
            terminal_header_rows,
            {
                pos
                for pos, alignment in enumerate(col_alignments)
                if alignment == HorizontalAlign.RIGHT
            },
            prefix_positions | suffix_positions,
        )
        all_row_blocks.append(blocks)

    all_block_lines = [
        [wrap_cell_text(b.text, b.width) for b in blocks] for blocks in all_row_blocks
    ]
    distribute_multi_row_span_lines(all_row_blocks, all_block_lines)

    # Render rows
    for r_idx, blocks in enumerate(all_row_blocks):
        block_lines = all_block_lines[r_idx]
        max_lines_in_row = max((len(bl) for bl in block_lines), default=1)

        for line_i in range(max_lines_in_row):
            formatted_blocks: list[str] = []
            for b_idx, b_info in enumerate(blocks):
                lines_list = block_lines[b_idx]
                v_align = (
                    b_info.cell.style.vertical_align
                    if b_info.cell is not None
                    else VerticalAlign.AUTO
                )
                if r_idx >= header_row_count:
                    txt = lines_list[line_i] if line_i < len(lines_list) else ""
                elif v_align == VerticalAlign.BOTTOM or (
                    v_align == VerticalAlign.AUTO and r_idx < header_row_count
                ):
                    pad = max_lines_in_row - len(lines_list)
                    txt = lines_list[line_i - pad] if line_i >= pad else ""
                elif v_align == VerticalAlign.MIDDLE:
                    pad = (max_lines_in_row - len(lines_list)) // 2
                    txt = (
                        lines_list[line_i - pad]
                        if pad <= line_i < pad + len(lines_list)
                        else ""
                    )
                else:
                    txt = lines_list[line_i] if line_i < len(lines_list) else ""
                formatted = format_cell_line(txt, b_info.width, align=b_info.alignment)
                formatted_blocks.append(formatted)
            row_line = col_sep.join(formatted_blocks).rstrip()
            if row_line or (lines and lines[-1] != ""):
                lines.append(row_line)

        row_div = format_row_divider(
            blocks,
            r_idx,
            header_row_count,
            header_divider_style,
            row_bot_borders,
            row_top_borders,
            budget,
            col_sep,
            prefix_positions,
            suffix_positions,
            table_has_affix_token,
            is_affix_footnote_token_fn=is_affix_footnote_token,
        )
        if row_div:
            lines.append(row_div)

    repair_rendered_affix_columns(lines)
    heal_divider_lines_from_templates(lines)
    prune_unanchored_divider_fragments(lines)

    # Trim common leading spaces across all non-empty table lines (with or without borders)
    body_lines = lines[1:]  # lines[0] is "<TABLE>"
    non_empty_body = [line for line in body_lines if line.strip()]
    if non_empty_body:
        min_leading = min(len(line) - len(line.lstrip(" ")) for line in non_empty_body)
        if min_leading > 0:
            lines = [lines[0]] + [
                (line[min_leading:] if line.strip() else "") for line in body_lines
            ]

    lines.append("</TABLE>")

    return TableRenderResult(
        ascii_text="\n".join(lines),
        resolved_grid=resolved_grid,
        confidence=confidence,
        diagnostics=tuple(str(d) for d in layout_diags) + tuple(veto_reasons),
    )


def render_grid_to_ascii(
    grid: list[list[str]],
    header_row_count: int = 1,
    alignments: list[HorizontalAlign] | None = None,
    budget: RenderBudget = DEFAULT_RENDER_BUDGET,
) -> str:
    """Render a 2D text matrix into canonical ASCII table format using geometry-first budgeting."""
    if not grid or not grid[0]:
        return ""

    num_cols = len(grid[0])
    if alignments is None:
        derived_alignments: list[HorizontalAlign] = []
        for c in range(num_cols):
            col_vals = [
                grid[r][c].strip()
                for r in range(header_row_count, len(grid))
                if c < len(grid[r]) and grid[r][c].strip()
            ]
            num_cnt = sum(1 for v in col_vals if is_numeric_cell(v))
            is_right = num_cnt > 0 and num_cnt >= len(col_vals) * 0.5
            derived_alignments.append(
                HorizontalAlign.RIGHT if is_right else HorizontalAlign.LEFT
            )
        alignments = derived_alignments

    widths, _ = compute_column_widths(grid, alignments, budget=budget)
    col_sep = " " * budget.column_spacing
    lines = ["<TABLE>"]

    for r_idx, row in enumerate(grid):
        block_lines = [
            wrap_cell_text(row[c] if c < len(row) else "", widths[c])
            for c in range(num_cols)
        ]
        max_lines = max((len(bl) for bl in block_lines), default=1)
        for line_i in range(max_lines):
            formatted_cells = []
            for c in range(num_cols):
                bl = block_lines[c]
                if r_idx < header_row_count:
                    pad = max_lines - len(bl)
                    txt = bl[line_i - pad] if line_i >= pad else ""
                else:
                    txt = bl[line_i] if line_i < len(bl) else ""
                formatted_cells.append(
                    format_cell_line(txt, widths[c], align=alignments[c])
                )
            lines.append(col_sep.join(formatted_cells).rstrip())

        if r_idx == header_row_count - 1 and header_row_count > 0:
            divs = ["-" * widths[c] for c in range(num_cols)]
            lines.append(col_sep.join(divs))

    lines.append("</TABLE>")
    return "\n".join(lines)


__all__ = [
    "render_grid_to_ascii",
    "render_source_table",
]
