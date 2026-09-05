"""Table DOM extraction, span tracking, and nested table isolation."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from defs.tables.ascii_html.css import parse_style_and_attributes
from defs.tables.ascii_html.model import (
    HorizontalAlign,
    SourceCell,
    SourceTable,
    SpanGroup,
)
from defs.tables.currencies import PREFIX_SYMBOLS
from defs.tables.tokens import is_numeric_cell
from defs.text.tokens import BULLET_MARKER_RE

if TYPE_CHECKING:
    from defs.text.html import FastHtmlNode


_NORMALIZE_TO_SPACE = frozenset(
    {
        "\u00a0",  # NO-BREAK SPACE
        "\u2007",  # FIGURE SPACE
        "\u202f",  # NARROW NO-BREAK SPACE
        "\u2009",  # THIN SPACE
    }
)

_STRIP_ZERO_WIDTH = frozenset(
    {
        "\u200b",  # ZERO WIDTH SPACE
        "\u200c",  # ZERO WIDTH NON-JOINER
        "\u200d",  # ZERO WIDTH JOINER
        "\ufeff",  # ZERO WIDTH NO-BREAK SPACE (BOM)
    }
)

_SENTENCE_END_RE = re.compile(r"[:.!?\)]\s*$")


def _collapse_non_structural_newlines(text: str) -> str:
    """Collapse soft wrapping newlines while preserving paragraphs and bullet/sentence breaks."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = re.split(r"\n\s*\n+", text.strip())
    out_paragraphs: list[str] = []

    for p in paragraphs:
        lines = p.split("\n")
        curr_line: list[str] = []
        p_lines: list[str] = []
        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue
            if not curr_line:
                curr_line.append(line_str)
            else:
                prev = curr_line[-1]
                first_word = line_str.split()[0]
                is_bullet = bool(BULLET_MARKER_RE.match(first_word))
                is_sentence_end = bool(_SENTENCE_END_RE.search(prev))
                is_capital = line_str[0].isupper() or line_str[0].isdigit()
                if is_bullet or (is_sentence_end and is_capital):
                    p_lines.append(" ".join(" ".join(curr_line).split()))
                    curr_line = [line_str]
                else:
                    curr_line.append(line_str)
        if curr_line:
            p_lines.append(" ".join(" ".join(curr_line).split()))
        if p_lines:
            out_paragraphs.append("\n".join(p_lines))

    return "\n\n".join(out_paragraphs)


def _normalize_whitespace(text: str, *, preserve_newlines: bool = False) -> str:
    for ch in _NORMALIZE_TO_SPACE:
        text = text.replace(ch, " ")
    for ch in _STRIP_ZERO_WIDTH:
        text = text.replace(ch, "")
    if not preserve_newlines:
        text = _collapse_non_structural_newlines(text)
    return text


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
    for node in table_node.raw_node.traverse():
        if (node.tag or "").lower() == "tr":
            # Check if this tr's closest parent table is our table_node
            curr = node.parent
            while curr is not None and (curr.tag or "").lower() != "table":
                curr = curr.parent
            if curr == table_node.raw_node:
                from defs.text.html import FastHtmlNode as FHN

                direct_rows.append(FHN(node))

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
            child_tables = child.css("table")
            is_nested = len(child_tables) > 0
            nested_idx: int | None = None

            if is_nested:
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

            cell_style = parse_style_and_attributes(child)
            try:
                colspan = max(1, int(child.get("colspan", "1") or "1"))
            except ValueError:
                colspan = 1
            try:
                rowspan = max(1, int(child.get("rowspan", "1") or "1"))
            except ValueError:
                rowspan = 1

            # Calculate visual indentation from CSS padding/margin/indent and non-breaking space prefixes
            inner_indent_px = 0.0
            for inner in child.css("div, p, span"):
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
            return not (len(t) == 4 and t.isdigit() and (1900 <= int(t) <= 2100))
        return False

    # Header band repairs only apply to top header rows (e.g. within top 5 rows)
    max_header_row = min(len(grid_matrix) - 1, 5)
    for row_idx in range(max_header_row):
        row = grid_matrix[row_idx]
        next_row = grid_matrix[row_idx + 1]

        # A header band row and its subheaders must not contain financial data
        if any(cell and _is_financial_data_token(cell.text) for cell in row):
            continue
        if any(cell and _is_financial_data_token(cell.text) for cell in next_row):
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


__all__ = [
    "build_span_matrix",
    "extract_source_table",
    "repair_header_band_spans",
]
