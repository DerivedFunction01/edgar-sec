"""Horizontal column band inference, alignment resolution, and spacer policy."""

from __future__ import annotations

from typing import TYPE_CHECKING

from defs.tables.ascii_html_v2.model import (
    BorderStyle,
    HorizontalAlign,
    SourceCell,
)
from defs.tables.tokens import (
    is_numeric_cell,
    is_prefix_token,
    is_suffix_token,
)

if TYPE_CHECKING:
    from defs.tables.ascii_html_v2.model import CellBox


def is_structural_spacer(
    col_idx: int,
    grid_matrix: list[list[SourceCell | None]],
) -> bool:
    """Determine whether an empty column has structural significance to retain.

    Retained when:
    - Starts a distinct cell origin in at least one row
    - Has non-empty text in at least one cell origin
    - Distinct border or background styling
    """
    has_origin = False
    has_content = False
    has_styling = False

    for row in grid_matrix:
        if col_idx >= len(row):
            continue
        cell = row[col_idx]
        if cell is None:
            continue

        # Check if this column is the start of a cell in this row
        is_origin = (col_idx == 0) or (col_idx > 0 and cell is not row[col_idx - 1])
        if is_origin:
            has_origin = True
            if cell.text.strip():
                has_content = True
                break

            # Check styling for empty origin cells (borders, background, or explicit spacer width on content rows)
            s = cell.style
            has_row_content = any(c is not None and bool(c.text.strip()) for c in row)
            if (
                s.background_color is not None
                or s.border_left_style != BorderStyle.NONE
                or s.border_right_style != BorderStyle.NONE
                or (s.width is not None and s.width > 5.0 and has_row_content)
            ):
                has_styling = True

    if not has_origin:
        # Submerged in spans across all rows: drop column
        return False

    return has_content or has_styling


def resolve_columns(
    grid_matrix: list[list[SourceCell | None]],
    box_matrix: list[list[CellBox | None]],
) -> tuple[list[int], list[HorizontalAlign], list[int]]:
    """Resolve active columns, column alignments, and pruned spacer columns.

    Returns:
    - active_col_indices: list of column indices to keep in the resolved grid
    - col_alignments: alignment per active column
    - spacer_col_indices: list of inert discarded column indices
    """
    if not grid_matrix or not grid_matrix[0]:
        return [], [], []

    num_cols = len(grid_matrix[0])
    num_rows = len(grid_matrix)

    active_cols: list[int] = []
    spacer_cols: list[int] = []

    for c_idx in range(num_cols):
        if is_structural_spacer(c_idx, grid_matrix):
            active_cols.append(c_idx)
        else:
            spacer_cols.append(c_idx)

    # If all columns were marked spacer, retain non-submerged origins
    if not active_cols:
        for c_idx in range(num_cols):
            has_origin = any(
                (c_idx == 0) or (c_idx > 0 and row[c_idx] is not row[c_idx - 1])
                for row in grid_matrix
                if c_idx < len(row) and row[c_idx] is not None
            )
            if has_origin:
                active_cols.append(c_idx)
            else:
                spacer_cols.append(c_idx)
        if not active_cols:
            active_cols = [0]
            spacer_cols = list(range(1, num_cols))

    # Infer alignment per active column
    col_alignments: list[HorizontalAlign] = []
    for c_idx in active_cols:
        numeric_count = 0
        text_count = 0
        explicit_align_votes: dict[HorizontalAlign, int] = {
            HorizontalAlign.LEFT: 0,
            HorizontalAlign.RIGHT: 0,
            HorizontalAlign.CENTER: 0,
        }

        for r_idx in range(num_rows):
            if c_idx >= len(grid_matrix[r_idx]):
                continue
            cell = grid_matrix[r_idx][c_idx]
            if cell is None:
                continue

            txt = cell.text.strip()
            if not txt:
                continue

            align = cell.style.text_align
            if align == HorizontalAlign.JUSTIFY:
                align = HorizontalAlign.LEFT
            if align in explicit_align_votes:
                explicit_align_votes[align] += 1

            if is_numeric_cell(txt):
                numeric_count += 1
            else:
                text_count += 1

        # Prefer explicit CSS alignment if voted; predominantly text columns default to LEFT
        if numeric_count == 0 and text_count > 0:
            if explicit_align_votes[HorizontalAlign.CENTER] > max(
                explicit_align_votes[HorizontalAlign.LEFT],
                explicit_align_votes[HorizontalAlign.RIGHT],
            ):
                col_alignments.append(HorizontalAlign.CENTER)
            elif (
                explicit_align_votes[HorizontalAlign.RIGHT]
                > explicit_align_votes[HorizontalAlign.LEFT]
                and explicit_align_votes[HorizontalAlign.RIGHT] >= text_count
            ):
                col_alignments.append(HorizontalAlign.RIGHT)
            else:
                col_alignments.append(HorizontalAlign.LEFT)
        elif (
            explicit_align_votes[HorizontalAlign.RIGHT]
            > explicit_align_votes[HorizontalAlign.LEFT]
        ):
            col_alignments.append(HorizontalAlign.RIGHT)
        elif explicit_align_votes[HorizontalAlign.CENTER] > max(
            explicit_align_votes[HorizontalAlign.LEFT],
            explicit_align_votes[HorizontalAlign.RIGHT],
        ):
            col_alignments.append(HorizontalAlign.CENTER)
        elif (
            explicit_align_votes[HorizontalAlign.LEFT]
            > explicit_align_votes[HorizontalAlign.RIGHT]
        ):
            col_alignments.append(HorizontalAlign.LEFT)
        elif numeric_count > 0 and (
            numeric_count >= text_count or numeric_count >= (num_rows - 2)
        ):
            col_alignments.append(HorizontalAlign.RIGHT)
        else:
            col_alignments.append(HorizontalAlign.LEFT)

    return active_cols, col_alignments, spacer_cols


def is_affix_footnote_token(txt: str) -> bool:
    """Return whether a token is a footnote/annotation marker."""
    if not txt:
        return False
    if txt in {"*", "**", "***", "****"}:
        return True
    return bool(txt.startswith("(") and txt.endswith(")") and len(txt) <= 5)


def identify_affix_columns(
    grid_matrix: list[list[SourceCell | None]],
    active_cols: list[int],
) -> tuple[set[int], set[int]]:
    """Identify which active column indices are pure prefix or suffix columns.

    Returns:
    - prefix_cols: set of active column positions (0..N-1) that contain only prefix tokens
    - suffix_cols: set of active column positions (0..N-1) that contain only suffix tokens
    """
    prefix_cols: set[int] = set()
    suffix_cols: set[int] = set()

    for pos, c_idx in enumerate(active_cols):
        non_empty_count = 0
        all_prefix = True
        all_suffix = True
        single_non_empty_count = 0
        single_all_prefix = True
        single_all_suffix = True

        for row in grid_matrix:
            if c_idx >= len(row) or row[c_idx] is None:
                continue
            cell = row[c_idx]
            txt = cell.text.strip()
            if not txt:
                continue
            non_empty_count += 1
            is_single = (c_idx == 0 or row[c_idx - 1] is not cell) and (
                c_idx + 1 >= len(row) or row[c_idx + 1] is not cell
            )
            if is_single:
                single_non_empty_count += 1
                if not is_prefix_token(txt):
                    single_all_prefix = False
                if not (is_suffix_token(txt) or is_affix_footnote_token(txt)):
                    single_all_suffix = False
            if not is_prefix_token(txt):
                all_prefix = False
            if not (is_suffix_token(txt) or is_affix_footnote_token(txt)):
                all_suffix = False

        if non_empty_count > 0:
            if (single_non_empty_count > 0 and single_all_prefix) or all_prefix:
                prefix_cols.add(pos)
            elif (single_non_empty_count > 0 and single_all_suffix) or all_suffix:
                suffix_cols.add(pos)

    return prefix_cols, suffix_cols


__all__ = [
    "identify_affix_columns",
    "is_structural_spacer",
    "resolve_columns",
]
