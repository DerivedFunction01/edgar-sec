"""Border segment extraction and multi-signal header boundary scoring."""

from __future__ import annotations

from defs.tables.ascii_html.model import (
    BorderSegment,
    BorderStyle,
    SourceCell,
)
from defs.tables.tokens import is_numeric_cell


def extract_border_segments(
    grid_matrix: list[list[SourceCell | None]],
    active_columns: list[int],
) -> list[BorderSegment]:
    """Extract discrete horizontal and vertical border segments from cell styles."""
    if not grid_matrix or not active_columns:
        return []

    num_rows = len(grid_matrix)
    segments: list[BorderSegment] = []

    # Map matrix column index to active column position
    col_map = {orig: pos for pos, orig in enumerate(active_columns)}

    for r_idx in range(num_rows):
        row = grid_matrix[r_idx]

        for orig_c in active_columns:
            if orig_c >= len(row):
                continue
            cell = row[orig_c]
            if cell is None:
                continue

            pos_c = col_map[orig_c]
            s = cell.style

            # Bottom border
            if s.border_bottom_style != BorderStyle.NONE and s.border_bottom_width > 0:
                segments.append(
                    BorderSegment(
                        row=r_idx,
                        start_column=pos_c,
                        end_column=pos_c,
                        edge="bottom",
                        width=s.border_bottom_width,
                        style=s.border_bottom_style,
                        color=s.border_bottom_color,
                    )
                )

            # Top border
            if s.border_top_style != BorderStyle.NONE and s.border_top_width > 0:
                segments.append(
                    BorderSegment(
                        row=r_idx,
                        start_column=pos_c,
                        end_column=pos_c,
                        edge="top",
                        width=s.border_top_width,
                        style=s.border_top_style,
                        color=s.border_top_color,
                    )
                )

    # Merge contiguous horizontal border segments on the same row & edge
    merged: list[BorderSegment] = []
    # Group by (row, edge, style, width, color)
    grouped: dict[
        tuple[int, str, BorderStyle, float, str | None], list[BorderSegment]
    ] = {}
    for seg in segments:
        key = (seg.row, seg.edge, seg.style, seg.width, seg.color)
        grouped.setdefault(key, []).append(seg)

    for (r, edge, style, width, color), seg_list in grouped.items():
        # Sort by start_column
        seg_list.sort(key=lambda s: s.start_column)
        cur_start = seg_list[0].start_column
        cur_end = seg_list[0].end_column

        for s in seg_list[1:]:
            if s.start_column <= cur_end + 1:
                cur_end = max(cur_end, s.end_column)
            else:
                merged.append(
                    BorderSegment(
                        row=r,
                        start_column=cur_start,
                        end_column=cur_end,
                        edge=edge,
                        width=width,
                        style=style,
                        color=color,
                    )
                )
                cur_start = s.start_column
                cur_end = s.end_column

        merged.append(
            BorderSegment(
                row=r,
                start_column=cur_start,
                end_column=cur_end,
                edge=edge,
                width=width,
                style=style,
                color=color,
            )
        )

    return merged


def score_header_boundary(
    grid_matrix: list[list[SourceCell | None]],
    active_columns: list[int],
    border_segments: list[BorderSegment],
    max_header_rows: int = 5,
) -> tuple[int, BorderStyle]:
    """Score potential header boundaries across the first N rows using multi-signal evidence.

    Signals evaluated per candidate split point (row 1..max_header_rows):
    - Explicit <th> presence (Weight: 5.0)
    - Continuous bottom border rule across >= 40% active columns (Weight: 4.0)
    - Border color transition (Weight: 3.5): Header bottom border color differs from body rows
    - Bold / font-weight transition (Weight: 2.5)
    - Background color transition (Weight: 1.5)

    Returns:
    - header_row_count: int (0 if no header boundary detected)
    - divider_style: BorderStyle (SOLID or DOUBLE)
    """
    if not grid_matrix or len(grid_matrix) < 2 or not active_columns:
        return 0, BorderStyle.SOLID

    num_rows = len(grid_matrix)
    num_cols = len(active_columns)
    candidate_limit = min(num_rows - 1, max_header_rows)

    best_split = 0
    best_score = 0.0
    best_style = BorderStyle.SOLID

    # Index bottom border coverage, style, and color per row (including top borders on row+1)
    bottom_border_coverage: dict[int, int] = {}
    bottom_border_styles: dict[int, BorderStyle] = {}
    bottom_border_colors: dict[int, str | None] = {}

    for seg in border_segments:
        if seg.edge == "bottom":
            effective_row = seg.row
        elif seg.edge == "top" and seg.row > 0:
            effective_row = seg.row - 1
        else:
            continue

        span_len = seg.end_column - seg.start_column + 1
        bottom_border_coverage[effective_row] = (
            bottom_border_coverage.get(effective_row, 0) + span_len
        )
        if seg.style == BorderStyle.DOUBLE:
            bottom_border_styles[effective_row] = BorderStyle.DOUBLE
        elif effective_row not in bottom_border_styles:
            bottom_border_styles[effective_row] = seg.style
        bottom_border_colors[effective_row] = seg.color

    for split in range(1, candidate_limit + 1):
        score = 0.0
        header_rows = grid_matrix[:split]
        body_row = grid_matrix[split] if split < num_rows else None
        last_header_row_idx = split - 1

        # Check if the last candidate header row contains numeric data (excluding 4-digit years)
        numeric_count = sum(
            1
            for c in active_columns
            if c < len(grid_matrix[last_header_row_idx])
            and grid_matrix[last_header_row_idx][c] is not None
            and is_numeric_cell(grid_matrix[last_header_row_idx][c].text.strip())
            and not (
                len(grid_matrix[last_header_row_idx][c].text.strip()) == 4
                and grid_matrix[last_header_row_idx][c].text.strip().isdigit()
                and (
                    1900
                    <= int(grid_matrix[last_header_row_idx][c].text.strip())
                    <= 2100
                )
            )
        )
        if numeric_count > 0:
            # Header rows cannot contain data amounts
            continue

        # 1. Explicit <th> cells in header region
        th_count = sum(
            1
            for r in header_rows
            for c in active_columns
            if c < len(r) and r[c] is not None and r[c].tag == "th"
        )
        if th_count > 0:
            score += 5.0 * (th_count / max(1, len(header_rows) * num_cols))

        # 2. Continuous bottom border on the last header row (split - 1)
        cov = bottom_border_coverage.get(last_header_row_idx, 0)
        cov_ratio = cov / max(1, num_cols)
        if cov_ratio >= 0.25:
            score += 5.0 * cov_ratio

        # 3. Border color transition: header border color differs from subsequent rows
        h_color = bottom_border_colors.get(last_header_row_idx)
        b_color = bottom_border_colors.get(split) if split < num_rows else None
        if h_color is not None:
            if b_color is None or b_color != h_color:
                score += 4.0
            else:
                score += 2.0

        # 4. Bold typography transition (header is bold, body is normal)
        header_bold_count = sum(
            1
            for r in header_rows
            for c in active_columns
            if c < len(r) and r[c] is not None and r[c].style.is_bold
        )
        header_bold_ratio = header_bold_count / max(1, len(header_rows) * num_cols)

        body_bold_count = (
            sum(
                1
                for c in active_columns
                if c < len(body_row)
                and body_row[c] is not None
                and body_row[c].style.is_bold
            )
            if body_row
            else 0
        )
        body_bold_ratio = body_bold_count / max(1, num_cols)

        if header_bold_ratio > 0.4 and body_bold_ratio < 0.4:
            score += 2.5 * (header_bold_ratio - body_bold_ratio)

        # 5. Background color transition
        header_bg_count = sum(
            1
            for r in header_rows
            for c in active_columns
            if c < len(r)
            and r[c] is not None
            and r[c].style.background_color is not None
        )
        if header_bg_count > 0:
            score += 1.5

        if score > best_score and score >= 2.0:
            best_score = score
            best_split = split
            best_style = bottom_border_styles.get(
                last_header_row_idx, BorderStyle.SOLID
            )

    return best_split, best_style


__all__ = [
    "extract_border_segments",
    "score_header_boundary",
]
