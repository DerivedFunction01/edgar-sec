"""Table DOM extraction, span tracking, and nested table isolation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from defs.tables.ascii_html.css import parse_style_and_attributes
from defs.tables.ascii_html.model import (
    HorizontalAlign,
    SourceCell,
    SourceTable,
    SpanGroup,
)
from defs.tables.ascii_html.text import (
    normalize_cell_whitespace as _normalize_whitespace,
)
from defs.tables.tokens import (
    PREFIX_SYMBOLS,
    is_numeric_cell,
    is_year_token,
)
from defs.text.html import FastHtmlNode

if TYPE_CHECKING:
    from defs.tables.ascii_html.blocks import RenderBlock

# O4: tag sets for bounded-DFS inner-indent scan
_INDENT_SOURCE_TAGS: frozenset[str] = frozenset({"div", "p", "span"})
_INDENT_STOP_TAGS: frozenset[str] = frozenset({"table", "tr", "td", "th"})


def _iter_indent_descendants(cell: FastHtmlNode):
    """Yield div/p/span raw selectolax Nodes within a cell without crossing table boundaries.

    Replaces ``cell.css('div, p, span')`` with a bounded DFS that avoids the
    overhead of CSS selector parsing and selectolax re-parenting of malformed cells.
    """
    stack = [c for c in cell.raw_node.iter(include_text=False) if c.tag]
    while stack:
        raw = stack.pop()
        tag = (raw.tag or "").lower()
        if tag in _INDENT_SOURCE_TAGS:
            yield raw
        if tag not in _INDENT_STOP_TAGS:
            stack.extend(c for c in raw.iter(include_text=False) if c.tag)


def extract_source_table(
    table_node: FastHtmlNode,
    table_index: int = 0,
    parent_table_index: int | None = None,
) -> tuple[SourceTable, list[SourceTable]]:
    """Extract a SourceTable and any nested child tables cleanly isolated from the parent.

    Nested tables found inside cells are registered as separate SourceTable instances
    and referenced by index from the containing SourceCell.
    """
    nested_tables: list[SourceTable] = []
    table_style = parse_style_and_attributes(table_node)

    # Find rows that belong DIRECTLY to this table (not to a nested child table)
    direct_rows: list[FastHtmlNode] = []
    for child in table_node.iter_children():
        tag = child.tag
        if tag == "tr":
            direct_rows.append(child)
        elif tag in ("tbody", "thead", "tfoot"):
            for subchild in child.iter_children():
                if subchild.tag == "tr":
                    direct_rows.append(subchild)

    extracted_rows: list[list[SourceCell]] = []

    for r_idx, row_node in enumerate(direct_rows):
        row_style = parse_style_and_attributes(row_node)
        if row_style.is_hidden:
            continue

        row_cells: list[SourceCell] = []
        c_idx = 0

        # Find cells that belong DIRECTLY to this row
        for child in row_node.iter_children():
            tag = child.tag
            if tag not in ("td", "th"):
                continue

            cell_style = parse_style_and_attributes(child)
            if cell_style.is_hidden:
                continue

            # Check for nested tables inside this cell
            is_nested = False
            nested_idx: int | None = None
            has_child_elements = child.raw_node.child is not None and (
                child.raw_node.child.tag is not None
                or child.raw_node.child.next is not None
            )
            if has_child_elements and child.raw_node.css_first("table") is not None:
                child_tables = child.css("table")
                if child_tables:
                    is_nested = True
                    for sub_t in child_tables:
                        sub_idx = len(nested_tables) + 1
                        sub_source, sub_nested = extract_source_table(
                            sub_t,
                            table_index=sub_idx,
                            parent_table_index=table_index,
                        )
                        nested_tables.append(sub_source)
                        nested_tables.extend(sub_nested)
                        if nested_idx is None:
                            nested_idx = sub_idx

            child_attrs = child.raw_node.attributes or {}
            try:
                colspan = max(1, int(child_attrs.get("colspan", "1") or "1"))
            except ValueError:
                colspan = 1
            try:
                rowspan = max(1, int(child_attrs.get("rowspan", "1") or "1"))
            except ValueError:
                rowspan = 1

            # Calculate visual indentation from CSS padding/margin/indent and non-breaking space prefixes
            inner_indent_px = 0.0
            if has_child_elements:
                # O4: bounded DFS instead of child.css() to avoid CSS selector overhead
                for inner in _iter_indent_descendants(child):
                    attrs = inner.attributes or {}
                    if "style" in attrs or "class" in attrs or "align" in attrs:
                        inner_s = parse_style_and_attributes(inner)
                        inner_indent_px += (
                            max(0.0, inner_s.padding_left)
                            + max(0.0, inner_s.text_indent)
                            + max(0.0, inner_s.margin_left)
                        )

            indent_px = (
                max(0.0, cell_style.padding_left)
                + max(0.0, cell_style.text_indent)
                + max(0.0, cell_style.margin_left)
                + inner_indent_px
            )
            css_indent = 0
            if indent_px >= 6.0:
                css_indent = min(8, int((indent_px + 2.0) / 8.0) * 2)

            raw_txt = child.text(separator=" ", strip=False)
            lstrip_txt = raw_txt.lstrip(" \t\u00a0")
            nbsp_count = len(raw_txt) - len(lstrip_txt)
            nbsp_indent = min(8, (nbsp_count // 2) * 2) if nbsp_count >= 2 else 0

            total_indent = max(css_indent, nbsp_indent)
            cell_text = child.text(separator="\n", strip=True)
            preserve_nl = cell_style.white_space in ("pre", "pre-wrap")
            cell_text = _normalize_whitespace(cell_text, preserve_newlines=preserve_nl)
            # Suppress indentation prefixes on numeric or right/center-aligned cells
            if is_numeric_cell(cell_text) or cell_style.text_align in (
                HorizontalAlign.RIGHT,
                HorizontalAlign.CENTER,
            ):
                total_indent = 0

            if total_indent > 0 and cell_text:
                cell_text = (" " * total_indent) + cell_text

            sc = SourceCell(
                row_index=r_idx,
                source_col_index=c_idx,
                tag=tag,
                text=cell_text,
                raw_attributes=dict(child.attributes),
                style=cell_style,
                colspan=colspan,
                rowspan=rowspan,
                is_nested_table_holder=is_nested,
                nested_table_index=nested_idx,
                indent_spaces=total_indent,
            )
            row_cells.append(sc)
            c_idx += 1

        if row_cells:
            extracted_rows.append(row_cells)

    source_table = SourceTable(
        table_index=table_index,
        parent_table_index=parent_table_index,
        raw_node=table_node,
        rows=tuple(tuple(r) for r in extracted_rows),
        style=table_style,
        attributes=dict(table_node.attributes),
    )

    return source_table, nested_tables


def build_span_matrix(
    source_table: SourceTable,
) -> tuple[list[list[SourceCell | None]], list[SpanGroup]]:
    """Build a 2D matrix mapping (row, col) grid slots accounting for rowspan and colspan.

    Returns:
    - grid_matrix: 2D list where each cell contains the owning SourceCell.
    - span_groups: list of SpanGroup instances describing multi-cell regions.
    """
    if not source_table.rows:
        return [], []

    # Estimate dimensions
    num_rows = len(source_table.rows)
    matrix: list[list[SourceCell | None]] = []
    span_groups: list[SpanGroup] = []

    for r in range(num_rows):
        matrix.append([])

    for r_idx, row in enumerate(source_table.rows):
        curr_col = 0
        for cell in row:
            # Advance past already occupied cells from previous rowspans
            while curr_col < len(matrix[r_idx]) and matrix[r_idx][curr_col] is not None:
                curr_col += 1

            # Expand rows in matrix if needed for rowspan
            target_r_end = r_idx + cell.rowspan
            while len(matrix) < target_r_end:
                matrix.append([])

            # Place cell across its colspan and rowspan
            c_start = curr_col
            c_end = curr_col + cell.colspan

            for r in range(r_idx, target_r_end):
                while len(matrix[r]) < c_end:
                    matrix[r].append(None)
                for c in range(c_start, c_end):
                    matrix[r][c] = cell

            if cell.colspan > 1 or cell.rowspan > 1:
                span_groups.append(
                    SpanGroup(
                        start_row=r_idx,
                        end_row=target_r_end - 1,
                        start_col=c_start,
                        end_col=c_end - 1,
                        source_cell=cell,
                    )
                )

            curr_col = c_end

    # Normalize matrix rows to equal length
    max_cols = max((len(r) for r in matrix), default=0)
    for row in matrix:
        while len(row) < max_cols:
            row.append(None)

    return matrix, span_groups


def repair_header_band_spans(
    grid_matrix: list[list[SourceCell | None]],
) -> None:
    """Align visible band labels to the logical header groups beneath them.

    Some SEC tables include hidden spacer cells whose declared ``colspan``
    does not line up with the visible repeated headers. In that case, a band
    label can cover only part of its logical repeated header group. The
    repair is intentionally text-agnostic: it applies to years, quarters,
    scenario labels, or other visible header text when the row below provides
    repeated multi-column groups.
    """
    from defs.tables.ascii_html.columns import is_affix_footnote_token
    from defs.tables.tokens import is_numeric_cell

    def _is_financial_data_token(text: str) -> bool:
        t = text.strip()
        if not t:
            return False
        if t in PREFIX_SYMBOLS or t == "%":
            return True
        if is_numeric_cell(t):
            # 4-digit years like 2024 or 2025 can be header labels
            return not is_year_token(t)
        return False

    # Header band repairs only apply to top header rows (e.g. within top 5 rows)
    max_header_row = min(len(grid_matrix) - 1, 5)
    row_has_financial = [
        any(cell and _is_financial_data_token(cell.text) for cell in grid_matrix[r])
        for r in range(max_header_row + 1)
    ]
    for row_idx in range(max_header_row):
        row = grid_matrix[row_idx]
        next_row = grid_matrix[row_idx + 1]

        # A header band row and its subheaders must not contain financial data
        if row_has_financial[row_idx] or row_has_financial[row_idx + 1]:
            continue

        band_cells: list[tuple[int, SourceCell]] = []
        seen_bands: set[int] = set()
        for col_idx, cell in enumerate(row):
            if (
                cell is None
                or id(cell) in seen_bands
                or not cell.text.strip()
                or cell.colspan <= 1
                or is_affix_footnote_token(cell.text.strip())
            ):
                continue
            band_cells.append((col_idx, cell))
            seen_bands.add(id(cell))

        if len(band_cells) < 2:
            continue

        header_cells: list[tuple[int, int]] = []
        seen_headers: set[int] = set()
        for col_idx, cell in enumerate(next_row):
            if (
                cell is None
                or id(cell) in seen_headers
                or not cell.text.strip()
                or cell.colspan <= 1
                or is_affix_footnote_token(cell.text.strip())
            ):
                continue
            if col_idx == 0:
                seen_headers.add(id(cell))
                continue
            end_col = col_idx
            while end_col + 1 < len(next_row) and next_row[end_col + 1] is cell:
                end_col += 1
            header_cells.append((col_idx, end_col))
            seen_headers.add(id(cell))

        if len(header_cells) < len(band_cells) * 2 or len(header_cells) % len(
            band_cells
        ):
            continue
        groups_per_band = len(header_cells) // len(band_cells)
        if groups_per_band < 2:
            continue

        for band_idx, (_, band_cell) in enumerate(band_cells):
            first_group = header_cells[band_idx * groups_per_band]
            last_group = header_cells[(band_idx + 1) * groups_per_band - 1]
            for col_idx in range(first_group[0], last_group[1] + 1):
                if col_idx < len(row):
                    # Never overwrite an existing cell with non-empty text from another source
                    target = row[col_idx]
                    if target is None or not target.text.strip() or target is band_cell:
                        row[col_idx] = band_cell


def distribute_multi_row_span_lines(
    all_row_blocks: list[list[RenderBlock]],
    all_block_lines: list[list[list[str]]],
) -> None:
    """Distribute wrapped lines of multi-row spanning cells across their row span."""
    from defs.tables.ascii_html.model import VerticalAlign
    from defs.tables.ascii_html.text import wrap_cell_text

    seen_cells: set[int] = set()
    for blocks in all_row_blocks:
        for b in blocks:
            cell = b.cell
            if cell is None or cell.rowspan <= 1 or id(cell) in seen_cells:
                continue
            seen_cells.add(id(cell))
            row_indices = [
                r
                for r, row_b in enumerate(all_row_blocks)
                if any(x.cell is cell for x in row_b)
            ]
            if len(row_indices) <= 1:
                continue

            full_lines = wrap_cell_text(cell.text, b.width)
            total_lines = len(full_lines)
            k = len(row_indices)

            min_heights: list[int] = []
            for r in row_indices:
                row_b = all_row_blocks[r]
                row_bl = all_block_lines[r]
                other_lens = [
                    len(row_bl[i])
                    for i, x in enumerate(row_b)
                    if x.cell is not cell
                    and (x.cell is None or x.cell.rowspan <= 1)
                    and bool(x.text.strip())
                ]
                min_heights.append(max(other_lens, default=1) if other_lens else 1)

            if total_lines <= 1:
                v_align = cell.style.vertical_align
                if v_align == VerticalAlign.MIDDLE:
                    target_r = row_indices[k // 2]
                elif v_align == VerticalAlign.BOTTOM:
                    target_r = row_indices[-1]
                else:
                    target_r = row_indices[0]
                for r in row_indices:
                    b_i = next(
                        i for i, x in enumerate(all_row_blocks[r]) if x.cell is cell
                    )
                    all_block_lines[r][b_i] = full_lines if r == target_r else []
            else:
                cur_sum = sum(min_heights)
                extra = max(0, total_lines - cur_sum)
                heights = list(min_heights)
                if extra > 0:
                    base_add = extra // k
                    rem = extra % k
                    for i in range(k):
                        heights[i] += base_add + (1 if i < rem else 0)

                offset = 0
                for i, r in enumerate(row_indices):
                    h = heights[i]
                    slice_l = full_lines[offset : offset + h]
                    offset += h
                    b_i = next(
                        j for j, x in enumerate(all_row_blocks[r]) if x.cell is cell
                    )
                    all_block_lines[r][b_i] = slice_l


__all__ = [
    "build_span_matrix",
    "distribute_multi_row_span_lines",
    "extract_source_table",
    "repair_header_band_spans",
]
