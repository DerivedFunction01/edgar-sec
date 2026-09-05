"""Render block data structure, grid extraction, and block fusion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from defs.tables.ascii_html.columns import is_affix_footnote_token
from defs.tables.ascii_html.model import HorizontalAlign, RenderBudget
from defs.tables.tokens import (
    CLOSING_DELIMITERS,
    is_numeric_cell,
    is_prefix_token,
    is_suffix_token,
)

if TYPE_CHECKING:
    from defs.tables.ascii_html.model import SourceCell


@dataclass(slots=True)
class RenderBlock:
    """A contiguous horizontal visual span within a rendered table row."""

    cell: SourceCell | None
    span_cols: list[int]
    width: int
    alignment: HorizontalAlign
    text: str


def extract_raw_grids_and_spans(
    grid_matrix: list[list[SourceCell | None]],
    active_cols: list[int],
) -> tuple[list[list[str]], list[list[str]], list[tuple[int, list[int], str]]]:
    """Extract 2D raw text grid and span constraints across active table columns."""
    raw_grid: list[list[str]] = []
    single_col_grid: list[list[str]] = []
    span_constraints: list[tuple[int, list[int], str]] = []

    for r_idx in range(len(grid_matrix)):
        row_txts: list[str] = []
        single_row_txts: list[str] = []
        i = 0
        while i < len(active_cols):
            c_pos = i
            c_idx = active_cols[c_pos]
            cell = (
                grid_matrix[r_idx][c_idx] if c_idx < len(grid_matrix[r_idx]) else None
            )

            span_c_indices = [c_pos]
            j = i + 1
            while j < len(active_cols):
                next_c_pos = j
                next_c_idx = active_cols[next_c_pos]
                next_cell = (
                    grid_matrix[r_idx][next_c_idx]
                    if next_c_idx < len(grid_matrix[r_idx])
                    else None
                )
                if cell is not None and next_cell is cell:
                    span_c_indices.append(next_c_pos)
                    j += 1
                else:
                    break

            if (
                cell is not None
                and r_idx > 0
                and c_idx < len(grid_matrix[r_idx - 1])
                and grid_matrix[r_idx - 1][c_idx] is cell
            ):
                txt = ""
            else:
                txt = cell.text if cell is not None else ""

            if len(span_c_indices) == 1:
                row_txts.append(txt)
                single_row_txts.append(txt)
            else:
                row_txts.append(txt)
                for _ in range(len(span_c_indices) - 1):
                    row_txts.append("")
                for _ in range(len(span_c_indices)):
                    single_row_txts.append("")
                if txt.strip():
                    span_constraints.append((r_idx, span_c_indices, txt.strip()))

            i = j

        raw_grid.append(row_txts)
        single_col_grid.append(single_row_txts)

    return raw_grid, single_col_grid, span_constraints


def build_row_blocks(
    grid_matrix: list[list[SourceCell | None]],
    r_idx: int,
    active_cols: list[int],
    visible_col_indices: list[int],
    col_widths: list[int],
    col_alignments: list[HorizontalAlign],
    raw_grid: list[list[str]],
    budget: RenderBudget,
) -> list[RenderBlock]:
    """Group consecutive visible columns sharing the same SourceCell into RenderBlocks."""
    blocks: list[RenderBlock] = []
    i = 0
    row = raw_grid[r_idx] if r_idx < len(raw_grid) else []
    seen_cells_in_row: set[int] = set()

    while i < len(visible_col_indices):
        c_pos = visible_col_indices[i]
        cell = (
            grid_matrix[r_idx][active_cols[c_pos]]
            if active_cols[c_pos] < len(grid_matrix[r_idx])
            else None
        )

        span_c_indices = [c_pos]
        j = i + 1
        while j < len(visible_col_indices):
            next_c_pos = visible_col_indices[j]
            next_cell = (
                grid_matrix[r_idx][active_cols[next_c_pos]]
                if active_cols[next_c_pos] < len(grid_matrix[r_idx])
                else None
            )
            if cell is not None and next_cell is cell:
                span_c_indices.append(next_c_pos)
                j += 1
            else:
                break

        block_w = sum(col_widths[c] for c in span_c_indices) + budget.column_spacing * (
            len(span_c_indices) - 1
        )

        if cell is not None and cell.style.text_align in (
            HorizontalAlign.LEFT,
            HorizontalAlign.RIGHT,
            HorizontalAlign.CENTER,
        ):
            b_align = cell.style.text_align
        elif len(span_c_indices) > 1:
            b_align = HorizontalAlign.CENTER
        else:
            b_align = col_alignments[c_pos]

        is_rowspan_continuation = (
            cell is not None
            and r_idx > 0
            and active_cols[c_pos] < len(grid_matrix[r_idx - 1])
            and grid_matrix[r_idx - 1][active_cols[c_pos]] is cell
        )

        if is_rowspan_continuation:
            block_txt = ""
            b_align = col_alignments[c_pos]
        elif cell is not None and id(cell) not in seen_cells_in_row:
            seen_cells_in_row.add(id(cell))
            if c_pos < len(row) and row[c_pos].strip():
                block_txt = row[c_pos]
            else:
                # Find text from any active column belonging to this cell in raw_grid, or fallback to cell.text
                found_txt = ""
                for active_col_idx, orig_c in enumerate(active_cols):
                    if (
                        orig_c < len(grid_matrix[r_idx])
                        and grid_matrix[r_idx][orig_c] is cell
                        and active_col_idx < len(row)
                        and row[active_col_idx].strip()
                    ):
                        found_txt = row[active_col_idx]
                        break
                block_txt = found_txt if found_txt else cell.text
        elif r_idx < len(raw_grid) and c_pos < len(row):
            block_txt = row[c_pos]
        else:
            block_txt = ""

        blocks.append(
            RenderBlock(
                cell=cell,
                span_cols=span_c_indices,
                width=block_w,
                alignment=b_align,
                text=block_txt,
            )
        )
        i = j

    return blocks


def fuse_data_affix_blocks(
    blocks: list[RenderBlock],
    r_idx: int,
    header_row_count: int,
    prefix_positions: set[int],
    suffix_positions: set[int],
    budget: RenderBudget,
) -> list[RenderBlock]:
    """Fuse adjacent prefix/suffix blocks in data rows safely."""
    is_data_row = r_idx >= header_row_count
    if not is_data_row:
        return blocks

    curr_blocks = blocks
    while True:
        fused_blocks: list[RenderBlock] = []
        b_idx = 0
        changed = False

        while b_idx < len(curr_blocks):
            curr_b = curr_blocks[b_idx]
            if b_idx + 1 < len(curr_blocks):
                next_b = curr_blocks[b_idx + 1]

                # 1. Prefix pair ($ + number)
                curr_is_prefix = (
                    len(curr_b.span_cols) == 1
                    and curr_b.span_cols[0] in prefix_positions
                    and next_b.span_cols[0] == curr_b.span_cols[0] + 1
                )
                if curr_is_prefix:
                    p_txt = curr_b.text.strip()
                    n_txt = next_b.text.strip()
                    is_safe_p = not p_txt or is_prefix_token(p_txt)
                    is_safe_n = (
                        not n_txt
                        or is_numeric_cell(n_txt)
                        or any(c in suffix_positions for c in next_b.span_cols)
                    )
                    if is_safe_p and is_safe_n:
                        combined_span = curr_b.span_cols + next_b.span_cols
                        combined_w = curr_b.width + budget.column_spacing + next_b.width
                        combined_txt = f"{p_txt} {n_txt}".strip() if p_txt else n_txt
                        fused_blocks.append(
                            RenderBlock(
                                cell=next_b.cell or curr_b.cell,
                                span_cols=combined_span,
                                width=combined_w,
                                alignment=HorizontalAlign.RIGHT,
                                text=combined_txt,
                            )
                        )
                        b_idx += 2
                        changed = True
                        continue

                # 2. Suffix pair (number + %)
                next_is_suffix = (
                    len(next_b.span_cols) == 1
                    and (
                        next_b.span_cols[0] in suffix_positions
                        or is_suffix_token(next_b.text.strip())
                    )
                    and next_b.span_cols[0] == curr_b.span_cols[-1] + 1
                )
                if next_is_suffix:
                    n_txt = curr_b.text.strip()
                    s_txt = next_b.text.strip()
                    is_safe_s = (
                        not s_txt
                        or is_suffix_token(s_txt)
                        or is_affix_footnote_token(s_txt)
                    )
                    is_safe_n = (
                        not n_txt or is_numeric_cell(n_txt) or n_txt.startswith("(")
                    )
                    if is_safe_s and is_safe_n:
                        combined_span = curr_b.span_cols + next_b.span_cols
                        combined_w = curr_b.width + budget.column_spacing + next_b.width
                        if s_txt in CLOSING_DELIMITERS:
                            combined_txt = f"{n_txt.rstrip()}{s_txt}"
                        else:
                            combined_txt = (
                                f"{n_txt} {s_txt}".strip() if s_txt else n_txt
                            )
                        fused_blocks.append(
                            RenderBlock(
                                cell=curr_b.cell or next_b.cell,
                                span_cols=combined_span,
                                width=combined_w,
                                alignment=HorizontalAlign.RIGHT,
                                text=combined_txt,
                            )
                        )
                        b_idx += 2
                        changed = True
                        continue

            fused_blocks.append(curr_b)
            b_idx += 1

        if not changed:
            return fused_blocks
        curr_blocks = fused_blocks


def fuse_empty_header_span_blocks(
    blocks: list[RenderBlock],
    r_idx: int,
    header_row_count: int,
    header_spans: list[set[int]],
    budget: RenderBudget,
) -> list[RenderBlock]:
    """Fuse empty spacer sub-blocks under a parent header span in data rows."""
    if r_idx < header_row_count or not header_spans:
        return blocks

    curr_blocks = blocks
    changed = True
    while changed:
        changed = False
        fused: list[RenderBlock] = []
        b_idx = 0
        while b_idx < len(curr_blocks):
            curr_b = curr_blocks[b_idx]
            if b_idx + 1 < len(curr_blocks):
                next_b = curr_blocks[b_idx + 1]
                comb_cols = set(curr_b.span_cols + next_b.span_cols)
                is_empty_one = (not curr_b.text.strip()) or (not next_b.text.strip())
                in_same_h_span = any(
                    comb_cols.issubset(h_span) for h_span in header_spans
                )

                if is_empty_one and in_same_h_span:
                    active_b = next_b if not curr_b.text.strip() else curr_b
                    combined_w = curr_b.width + budget.column_spacing + next_b.width
                    combined_span = curr_b.span_cols + next_b.span_cols
                    fused.append(
                        RenderBlock(
                            cell=active_b.cell,
                            span_cols=combined_span,
                            width=combined_w,
                            alignment=active_b.alignment,
                            text=active_b.text,
                        )
                    )
                    b_idx += 2
                    changed = True
                    continue
            fused.append(curr_b)
            b_idx += 1
        curr_blocks = fused

    return curr_blocks


__all__ = [
    "RenderBlock",
    "build_row_blocks",
    "extract_raw_grids_and_spans",
    "fuse_data_affix_blocks",
    "fuse_empty_header_span_blocks",
]
