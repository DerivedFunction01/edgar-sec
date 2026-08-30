"""Generic text-based ASCII/SGML table layout builder and HTML grid converter."""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass

_RE_NUMERIC_CELL = re.compile(r"^[\$\€\£]?\s*\(?[\d,\.]+\)?%?$")


@dataclass
class GenericTable:
    """A generic class for building formatted text-based tables with SEC tags.

    Responsible only for the layout and formatting, not data preparation.
    """

    headers: list[str] | list[list[str]]
    data_rows: list[list[str]]
    widths: list[int]
    alignments: list[str]  # 'l' for left, 'r' for right, 'c' for center
    title: str

    def _format_row_with_wrapping(
        self,
        cells: list[str] | list[list[str]],
        widths: list[int],
        alignments: list[str],
    ) -> list[str]:
        """Format a single logical row into multiple physical lines with text wrapping."""
        wrapped_cells = []
        max_lines = 0
        for i, cell_content in enumerate(cells):
            if i >= len(widths):
                break
            text_val = (
                " ".join(cell_content)
                if isinstance(cell_content, list)
                else str(cell_content)
            )
            lines = textwrap.wrap(text_val, width=widths[i], break_long_words=False)
            if not lines:  # Handle empty cells
                lines = [""]
            wrapped_cells.append(lines)
            max_lines = max(max_lines, len(lines))

        for lines in wrapped_cells:
            while len(lines) < max_lines:
                lines.append("")

        output_lines = []
        for i in range(max_lines):
            row_parts = []
            for j, lines in enumerate(wrapped_cells):
                if j >= len(widths):
                    break
                align = alignments[j] if j < len(alignments) else "l"
                if align == "l":
                    row_parts.append(lines[i].ljust(widths[j]))
                elif align == "c":
                    row_parts.append(lines[i].center(widths[j]))
                else:  # 'r'
                    row_parts.append(lines[i].rjust(widths[j]))
            output_lines.append("  ".join(row_parts).rstrip())
        return output_lines

    def build(self) -> str:
        """Build the final table string with SEC tags."""
        header_lines = []
        if self.headers and isinstance(self.headers[0], list):
            for header_row in self.headers:
                assert isinstance(header_row, list)
                header_lines.extend(
                    self._format_row_with_wrapping(
                        header_row, self.widths, self.alignments
                    )
                )
        else:
            assert all(isinstance(h, str) for h in self.headers)
            header_lines.extend(
                self._format_row_with_wrapping(
                    self.headers, self.widths, self.alignments
                )
            )

        separator = "  ".join(["-" * w for w in self.widths])
        first_w = self.widths[0] if self.widths else 0
        first_marker = (
            "<C>" if (self.alignments and self.alignments[0] == "r") else "<S>"
        )
        sec_tags_line = (
            first_marker.ljust(first_w + 2)
            + "".join(["<C>".ljust(w + 2) for w in self.widths[1:]]).rstrip()
        )

        all_rows = header_lines + [separator, sec_tags_line]
        for row_data in self.data_rows:
            all_rows.extend(
                self._format_row_with_wrapping(row_data, self.widths, self.alignments)
            )

        caption_block = f"<CAPTION>\n{self.title}</CAPTION>\n\n" if self.title else ""
        return f"\n\n<TABLE>\n{caption_block}" + "\n".join(all_rows) + "\n</TABLE>\n\n"


@dataclass
class HTMLTableConverter:
    """Converts a 2D list of strings (from a parsed HTML table) into a GenericTable."""

    grid: list[list[str]]
    title: str = ""
    header_row_count: int = 1
    max_text_col_width: int = 60
    max_num_col_width: int = 18

    def _trim_empty_columns(self, grid: list[list[str]]) -> list[list[str]]:
        """Trim columns that are completely empty strings across all rows."""
        if not grid:
            return []
        num_cols = max(len(r) for r in grid)
        padded = [row + [""] * (num_cols - len(row)) for row in grid]
        non_empty_cols = [
            c
            for c in range(num_cols)
            if any(padded[r][c].strip() for r in range(len(padded)))
        ]
        if not non_empty_cols:
            return []
        return [[padded[r][c] for c in non_empty_cols] for r in range(len(padded))]

    def _calculate_widths_and_alignments(
        self, clean_grid: list[list[str]], split_idx: int
    ) -> tuple[list[int], list[str]]:
        """Calculate dynamic column alignments and capped column widths."""
        if not clean_grid:
            return [], []

        num_cols = len(clean_grid[0])
        data_rows = (
            clean_grid[split_idx:] if split_idx < len(clean_grid) else clean_grid
        )

        alignments = []
        widths = [0] * num_cols

        for c in range(num_cols):
            # Check numerical ratio in data cells
            col_data_cells = [
                r[c].strip() for r in data_rows if len(r) > c and r[c].strip()
            ]
            num_count = sum(
                1
                for cell in col_data_cells
                if _RE_NUMERIC_CELL.match(cell) or cell in ("—", "-", "–")
            )
            has_text = any(
                re.search(r"[a-zA-Z]", cell) for cell in col_data_cells
            )
            if c == 0 and has_text:
                is_numeric = False
            else:
                is_numeric = bool(
                    col_data_cells and (num_count / len(col_data_cells) >= 0.50)
                )

            alignments.append("r" if is_numeric else "l")

            # Determine max width with capping
            max_len = 0
            for row in clean_grid:
                if c < len(row):
                    max_len = max(max_len, len(row[c]))

            cap = self.max_num_col_width if is_numeric else self.max_text_col_width
            widths[c] = max(1, min(max_len, cap))

        return widths, alignments

    def to_generic_table(self) -> GenericTable:
        clean_grid = self._trim_empty_columns(self.grid)
        if not clean_grid:
            return GenericTable(
                headers=[],
                data_rows=[],
                widths=[],
                alignments=[],
                title=self.title,
            )

        split_idx = self.header_row_count if self.header_row_count > 0 else 1
        split_idx = min(split_idx, len(clean_grid))

        headers = clean_grid[:split_idx]
        data_rows = clean_grid[split_idx:]

        if not headers and data_rows:
            headers = [data_rows.pop(0)]

        widths, alignments = self._calculate_widths_and_alignments(
            clean_grid, split_idx
        )

        return GenericTable(
            headers=headers,
            data_rows=data_rows,
            widths=widths,
            alignments=alignments,
            title=self.title,
        )


__all__ = ["GenericTable", "HTMLTableConverter"]
