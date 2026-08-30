"""Generic text-based ASCII/SGML table layout builder and HTML grid converter."""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass

from bs4 import BeautifulSoup, Comment, FeatureNotFound

from .patterns import (
    BULLET_MARKER_RE,
    FOOTNOTE_RE,
    HIDDEN_ELEMENT_STYLE_RE,
    PAREN_SPACES_RE,
    YEAR_TOKEN_RE,
)
from .tokens import (
    PREFIX_SYMBOLS,
    PREFIX_TOKENS,
    SUFFIX_TOKENS,
    is_numeric_cell,
)


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
            num_count = sum(1 for cell in col_data_cells if is_numeric_cell(cell))
            has_text = any(re.search(r"[a-zA-Z]", cell) for cell in col_data_cells)
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


def _cell_text(cell: object) -> str:
    text = cell.get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    text = PAREN_SPACES_RE.sub(r"(\1)", text)
    return re.sub(r"^\$\s+(\d)", r"$\1", text)


def _span_grid(table: object) -> list[list[str]]:
    occupied: dict[tuple[int, int], str] = {}
    rows = table.find_all("tr")
    for r, tr in enumerate(rows):
        c = 0
        for cell in tr.find_all(["td", "th"]):
            while (r, c) in occupied:
                c += 1
            try:
                colspan = max(1, int(cell.get("colspan", 1)))
                rowspan = max(1, int(cell.get("rowspan", 1)))
            except (TypeError, ValueError):
                colspan = rowspan = 1
            occupied[(r, c)] = _cell_text(cell)
            for rr in range(r, r + rowspan):
                for cc in range(c, c + colspan):
                    occupied.setdefault((rr, cc), "")
            c += colspan
    if not occupied:
        return []
    max_r = max(r for r, _ in occupied) + 1
    max_c = max(c for _, c in occupied) + 1
    return [
        [occupied.get((r, c), "") for c in range(max_c)]
        for r in range(max_r)
        if any(occupied.get((r, c), "").strip() for c in range(max_c))
    ]


def _is_section(row: list[str]) -> bool:
    cells = [cell.strip().lower() for cell in row if cell.strip()]
    return bool(cells) and all(not is_numeric_cell(cell) for cell in cells)


def _heal_grid(grid: list[list[str]]) -> tuple[list[list[str]], int]:
    if not grid:
        return [], 0
    width = max(map(len, grid))
    rows = [row + [""] * (width - len(row)) for row in grid]
    header_count = 1
    for i, row in enumerate(rows):
        values = [cell.strip() for cell in row if cell.strip()]
        numeric = sum(
            is_numeric_cell(cell) and not YEAR_TOKEN_RE.match(cell) for cell in values
        )
        if values and numeric / len(values) >= 0.25:
            header_count = i
            break

    drop: set[int] = set()
    for c in range(1, width):
        cells = [
            rows[r][c].strip()
            for r in range(header_count, len(rows))
            if rows[r][c].strip() and not _is_section(rows[r])
        ]
        if (
            cells
            and len(cells) <= (len(rows) - header_count) * 0.6
            and all(FOOTNOTE_RE.match(cell) for cell in cells)
        ):
            for r in range(header_count, len(rows)):
                if rows[r][c].strip() and not _is_section(rows[r]):
                    for left in range(c - 1, -1, -1):
                        if rows[r][left].strip() and left not in drop:
                            rows[r][left] += " " + rows[r][c].strip()
                            break
            drop.add(c)

    for c in range(1, width):
        if c in drop:
            continue
        cells = [
            rows[r][c].strip()
            for r in range(header_count, len(rows))
            if rows[r][c].strip() and not _is_section(rows[r])
        ]
        if cells and all(cell.casefold() in SUFFIX_TOKENS for cell in cells):
            for r in range(header_count, len(rows)):
                if rows[r][c].strip() and not _is_section(rows[r]):
                    for left in range(c - 1, -1, -1):
                        if rows[r][left].strip() and left not in drop:
                            suffix = rows[r][c].strip()
                            rows[r][left] += (
                                "" if suffix.startswith(("%", ")")) else " "
                            ) + suffix
                            break
            drop.add(c)

    for c in range(width - 1):
        if c in drop:
            continue
        cells = [
            rows[r][c].strip()
            for r in range(header_count, len(rows))
            if rows[r][c].strip() and not _is_section(rows[r])
        ]
        if cells and all(
            cell in PREFIX_SYMBOLS or cell in PREFIX_TOKENS for cell in cells
        ):
            for r in range(header_count, len(rows)):
                if rows[r][c].strip() and not _is_section(rows[r]):
                    for right in range(c + 1, width):
                        if rows[r][right].strip() and right not in drop:
                            prefix = rows[r][c].strip()
                            rows[r][right] = (
                                prefix
                                + (
                                    ""
                                    if prefix in PREFIX_SYMBOLS or prefix == "("
                                    else " "
                                )
                                + rows[r][right].strip()
                            )
                            break
            drop.add(c)

    kept = [
        c
        for c in range(width)
        if c not in drop and any(rows[r][c].strip() for r in range(len(rows)))
    ]
    # Keep labels from structural columns when their data is folded right.
    for c in sorted(drop):
        for r in range(header_count):
            label = rows[r][c].strip()
            if not label:
                continue
            destination = next((target for target in kept if target > c), None)
            if destination is None:
                destination = next(
                    (target for target in reversed(kept) if target < c), None
                )
            if destination is not None:
                rows[r][destination] = " ".join(
                    part for part in (rows[r][destination].strip(), label) if part
                )
    return [
        [PAREN_SPACES_RE.sub(r"(\1)", rows[r][c].strip()) for c in kept]
        for r in range(len(rows))
    ], header_count


def convert_html_tables_to_ascii(html_content: str) -> str:
    """Convert valid HTML financial tables into standardized ASCII tables."""
    try:
        soup = BeautifulSoup(html_content, "lxml")
    except FeatureNotFound:  # pragma: no cover - parser availability varies
        soup = BeautifulSoup(html_content, "html.parser")
    for element in soup(
        ["head", "script", "style", "title", "meta", "noscript", "ix:hidden"]
    ):
        element.decompose()
    for element in soup.find_all(style=HIDDEN_ELEMENT_STYLE_RE):
        element.decompose()
    for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
        comment.extract()

    for table in list(soup.find_all("table")):
        rows = table.find_all("tr")
        if len(rows) <= 1:
            table.unwrap()
            continue
        cells = table.find_all(["td", "th"])
        full_text = table.get_text(" ", strip=True)
        bullet_rows = []
        for row in rows:
            row_cells = row.find_all(["td", "th"])
            if len(row_cells) != 2:
                break
            marker = _cell_text(row_cells[0])
            if not BULLET_MARKER_RE.match(marker) or len(marker) > 6:
                break
            bullet_rows.append(f"• {_cell_text(row_cells[1])}")
        else:
            if bullet_rows:
                table.replace_with(
                    soup.new_string("\n" + "\n".join(bullet_rows) + "\n")
                )
                continue
        if (
            "item" in full_text.lower()
            and "page" in full_text.lower()
            and "part i" in full_text.lower()
        ):
            table.unwrap()
            continue
        non_empty = [_cell_text(cell) for cell in cells if _cell_text(cell)]
        numeric = sum(is_numeric_cell(cell) for cell in non_empty)
        if len(rows) < 3 or not non_empty or numeric / len(non_empty) < 0.15:
            table.unwrap()
            continue
        grid, header_count = _heal_grid(_span_grid(table))
        if not grid or len(grid[0]) <= 1:
            table.unwrap()
            continue
        table.replace_with(
            soup.new_string(
                HTMLTableConverter(grid=grid, header_row_count=max(1, header_count))
                .to_generic_table()
                .build()
            )
        )
    return soup.get_text(separator="\n")


__all__ = ["GenericTable", "HTMLTableConverter", "convert_html_tables_to_ascii"]
