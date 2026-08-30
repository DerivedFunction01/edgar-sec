"""Generic text-based ASCII/SGML table layout builder and HTML grid converter."""

from __future__ import annotations

import textwrap
from dataclasses import dataclass


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
                align = alignments[j]
                if align == "l":
                    row_parts.append(lines[i].ljust(widths[j]))
                elif align == "c":
                    row_parts.append(lines[i].center(widths[j]))
                else:  # 'r'
                    row_parts.append(lines[i].rjust(widths[j]))
            output_lines.append("  ".join(row_parts))
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
        sec_tags_line = (
            "<S>".ljust(first_w + 2)
            + "".join(["<C>".ljust(w + 2) for w in self.widths[1:]]).rstrip()
        )

        all_rows = header_lines + [separator, sec_tags_line]
        for row_data in self.data_rows:
            all_rows.extend(
                self._format_row_with_wrapping(row_data, self.widths, self.alignments)
            )

        return (
            f"\n\n<TABLE>\n<CAPTION>\n{self.title}</CAPTION>\n\n"
            + "\n".join(all_rows)
            + "\n</TABLE>\n\n"
        )


@dataclass
class HTMLTableConverter:
    """Converts a 2D list of strings (from a parsed HTML table) into a GenericTable."""

    grid: list[list[str]]
    title: str = ""
    header_row_count: int = 1

    def _calculate_widths_and_alignments(self) -> tuple[list[int], list[str]]:
        """Calculate column widths and default alignments from the grid."""
        if not self.grid:
            return [], []

        num_cols = max(len(row) for row in self.grid) if self.grid else 0
        widths = [0] * num_cols
        for row in self.grid:
            for i, cell in enumerate(row):
                if i < num_cols:
                    widths[i] = max(widths[i], len(cell))

        widths = [max(1, w) for w in widths]
        alignments = ["l"] + ["r"] * (num_cols - 1)
        return widths, alignments

    def to_generic_table(self) -> GenericTable:
        if not self.grid:
            return GenericTable(
                headers=[], data_rows=[], widths=[], alignments=[], title=self.title
            )

        if self.header_row_count > 0:
            split_idx = self.header_row_count
        else:
            split_idx = 0
            for i, row in enumerate(self.grid):
                if row and row[0].strip():
                    split_idx = i
                    break
            if split_idx == 0:
                split_idx = 1

        split_idx = min(split_idx, len(self.grid))

        headers = self.grid[:split_idx]
        data_rows = self.grid[split_idx:]

        if not headers and data_rows:
            headers = [data_rows.pop(0)]

        widths, alignments = self._calculate_widths_and_alignments()

        return GenericTable(
            headers=headers,
            data_rows=data_rows,
            widths=widths,
            alignments=alignments,
            title=self.title,
        )


__all__ = ["GenericTable", "HTMLTableConverter"]
