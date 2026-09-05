"""Cell coordinate estimation and geometric interval math."""

from __future__ import annotations

from typing import TYPE_CHECKING

from defs.tables.ascii_html_v2.model import (
    CellBox,
    SourceCell,
    SourceTable,
)

if TYPE_CHECKING:
    from defs.tables.ascii_html_v2.model import SpanGroup


def estimate_table_geometry(
    source_table: SourceTable,
    grid_matrix: list[list[SourceCell | None]],
    span_groups: list[SpanGroup],
) -> list[list[CellBox | None]]:
    """Estimate physical 2D bounding boxes (left, right, top, bottom) for every cell in the grid."""
    if not grid_matrix or not grid_matrix[0]:
        return []

    num_rows = len(grid_matrix)
    num_cols = len(grid_matrix[0])

    # 1. Estimate base column widths
    col_explicit_widths: list[float | None] = [None] * num_cols
    col_content_widths: list[float] = [0.0] * num_cols

    for r_idx in range(num_rows):
        for c_idx in range(num_cols):
            cell = grid_matrix[r_idx][c_idx]
            if cell is None:
                continue

            # Only 1-column cells establish direct column width constraints
            if cell.colspan == 1:
                w = cell.style.width
                if w is not None and not cell.style.is_percent_width:
                    curr = col_explicit_widths[c_idx]
                    col_explicit_widths[c_idx] = max(curr or 0.0, w)

                text_len = float(len(cell.text))
                pad = cell.style.padding_left + cell.style.padding_right
                indent = cell.style.text_indent
                total_w = text_len * 8.0 + pad + indent  # Approx 8px per char
                col_content_widths[c_idx] = max(col_content_widths[c_idx], total_w)

    # Resolve final pixel column widths
    resolved_col_widths: list[float] = []
    for c_idx in range(num_cols):
        exp = col_explicit_widths[c_idx]
        cont = col_content_widths[c_idx]
        if exp is not None and exp > 0:
            resolved_col_widths.append(max(exp, cont))
        elif cont > 0:
            resolved_col_widths.append(cont)
        else:
            resolved_col_widths.append(20.0)  # Minimum fallback column width

    # Compute column left and right offsets
    col_lefts: list[float] = [0.0] * num_cols
    col_rights: list[float] = [0.0] * num_cols
    curr_x = 0.0
    for c_idx in range(num_cols):
        w = resolved_col_widths[c_idx]
        col_lefts[c_idx] = curr_x
        col_rights[c_idx] = curr_x + w
        curr_x += w

    # 2. Estimate row heights and tops/bottoms
    row_heights: list[float] = [20.0] * num_rows  # Base line height
    for r_idx in range(num_rows):
        max_h = 20.0
        for c_idx in range(num_cols):
            cell = grid_matrix[r_idx][c_idx]
            if cell is not None and cell.rowspan == 1:
                h = cell.style.height
                if h is not None and h > max_h:
                    max_h = h
                pad = cell.style.padding_top + cell.style.padding_bottom
                max_h = max(max_h, pad + 20.0)
        row_heights[r_idx] = max_h

    row_tops: list[float] = [0.0] * num_rows
    row_bottoms: list[float] = [0.0] * num_rows
    curr_y = 0.0
    for r_idx in range(num_rows):
        h = row_heights[r_idx]
        row_tops[r_idx] = curr_y
        row_bottoms[r_idx] = curr_y + h
        curr_y += h

    # 3. Construct CellBoxes
    box_matrix: list[list[CellBox | None]] = [
        [None] * num_cols for _ in range(num_rows)
    ]
    seen_cells: set[int] = set()

    for r_idx in range(num_rows):
        for c_idx in range(num_cols):
            cell = grid_matrix[r_idx][c_idx]
            if cell is None:
                continue

            cell_id = id(cell)
            if cell_id in seen_cells:
                # Find the existing box for this spanning cell
                continue
            seen_cells.add(cell_id)

            r_end = min(num_rows - 1, r_idx + cell.rowspan - 1)
            c_end = min(num_cols - 1, c_idx + cell.colspan - 1)

            left = col_lefts[c_idx] + cell.style.padding_left
            right = col_rights[c_end] - cell.style.padding_right
            top = row_tops[r_idx] + cell.style.padding_top
            bottom = row_bottoms[r_end] - cell.style.padding_bottom

            confidence = 1.0
            if cell.style.width is not None or cell.style.height is not None:
                confidence = 1.0
            elif cell.colspan > 1 or cell.rowspan > 1:
                confidence = 0.90
            else:
                confidence = 0.80

            box = CellBox(
                left=left,
                right=right,
                top=top,
                bottom=bottom,
                confidence=confidence,
                source_cell=cell,
            )

            # Assign box across all cells it spans
            for r in range(r_idx, r_end + 1):
                for c in range(c_idx, c_end + 1):
                    box_matrix[r][c] = box

    return box_matrix


__all__ = [
    "estimate_table_geometry",
]
