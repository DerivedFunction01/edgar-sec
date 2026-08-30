"""Generic text-based ASCII/SGML table layout builder and HTML grid converter."""

from __future__ import annotations

import re
import sys
import textwrap
from dataclasses import dataclass

from bs4 import BeautifulSoup, Comment, FeatureNotFound

from .grid_repairs import SpanGroup, apply_grid_repairs
from .patterns import (
    BULLET_MARKER_RE,
    HIDDEN_ELEMENT_STYLE_RE,
    NUMERIC_PERCENT_SPACE_RE,
    PAREN_SPACES_RE,
    YEAR_TOKEN_RE,
)
from .tokens import is_numeric_cell


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

        split_idx = max(0, self.header_row_count)
        split_idx = min(split_idx, len(clean_grid))

        headers = clean_grid[:split_idx]
        data_rows = clean_grid[split_idx:]

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
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    text = re.sub(r"\b([A-Z]) (?=[a-z])", r"\1", text)
    text = re.sub(r"\.{2,}", " ", text)
    text = PAREN_SPACES_RE.sub(r"(\1)", text)
    return re.sub(r"^\$\s+(\d)", r"$\1", text)


def _registration_table_template(
    source_grid: list[list[str]],
) -> str | None:
    """Render the stable three-column registered-securities table layout."""
    if len(source_grid) < 2:
        return None

    compact = [[cell for cell in row if cell.strip()] for row in source_grid]
    if any(len(row) != 3 for row in compact):
        return None

    normalized_headers = tuple(
        re.sub(r"\s+", " ", cell).strip().casefold() for cell in compact[0]
    )
    if (
        normalized_headers[0] != "title of each class"
        or normalized_headers[1] not in {"trading symbol", "trading symbol(s)",  "trading symbols"}
        or normalized_headers[2]
        != "name of each exchange on which registered"
    ):
        return None

    return (
        HTMLTableConverter(grid=compact, header_row_count=1)
        .to_generic_table()
        .build()
    )


def _span_grid(
    table: object, *, with_spans: bool = False
) -> list[list[str]] | tuple[list[list[str]], list[SpanGroup]]:
    occupied: dict[tuple[int, int], str] = {}
    span_groups: list[SpanGroup] = []
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
            if colspan > 1:
                span_groups.append((r, c, c + colspan, _cell_text(cell)))
            for rr in range(r, r + rowspan):
                for cc in range(c, c + colspan):
                    occupied.setdefault((rr, cc), "")
            c += colspan
    if not occupied:
        return []
    max_r = max(r for r, _ in occupied) + 1
    max_c = max(c for _, c in occupied) + 1
    included_rows = [
        r
        for r in range(max_r)
        if any(occupied.get((r, c), "").strip() for c in range(max_c))
    ]
    grid = [[occupied.get((r, c), "") for c in range(max_c)] for r in included_rows]
    if with_spans:
        row_map = {source: target for target, source in enumerate(included_rows)}
        span_groups = [
            (row_map[row], start, end, label)
            for row, start, end, label in span_groups
            if row in row_map
        ]
        return grid, span_groups
    return grid


def _signature_template(table: object) -> str | None:
    source_grid, _ = _span_grid(table, with_spans=True)
    if not source_grid:
        return None
    all_text = " ".join(cell for row in source_grid for cell in row if cell)
    if "/s/" not in all_text:
        return None
    date_pattern = re.compile(r"\b\d{1,2},\s*\d{4}\b")
    header_index = next(
        (
            index
            for index, row in enumerate(source_grid)
            if (
                {"title", "date"}.issubset({cell.casefold() for cell in row if cell})
                and any(cell.casefold() in {"name", "signature"} for cell in row if cell)
            )
        ),
        None,
    )
    if header_index is not None:
        header = source_grid[header_index]
        starts = [
            index
            for index, cell in enumerate(header)
            if cell.casefold() in {"name", "signature", "title", "date"}
        ]
        starts.sort()
        groups = [
            (
                starts[index],
                starts[index + 1] if index + 1 < len(starts) else len(header),
            )
            for index in range(len(starts))
        ]
        records: list[list[str]] = []
        for row in source_grid[header_index + 1 :]:
            values = [
                " ".join(cell for cell in row[start:end] if cell).strip()
                for start, end in groups
            ]
            if not any(values):
                continue
            if records and not date_pattern.search(values[-1]):
                records[-1] = [
                    " ".join(
                        part for part in (records[-1][index], values[index]) if part
                    )
                    for index in range(3)
                ]
            else:
                records.append(values)
        header_name = "Signature" if "signature" in header else "Name"
        return (
            HTMLTableConverter(
                grid=[[header_name, "Title", "Date"], *records], header_row_count=1
            )
            .to_generic_table()
            .build()
        )

    if "by:" not in all_text.casefold():
        return None
    midpoint = max(1, len(source_grid[0]) // 2)
    rows = []
    for row in source_grid:
        left = " ".join(cell for cell in row[:midpoint] if cell).strip()
        right = " ".join(cell for cell in row[midpoint:] if cell).strip()
        if left or right:
            rows.append([left, right])
    return HTMLTableConverter(grid=rows, header_row_count=0).to_generic_table().build()


def _heal_grid(
    grid: list[list[str]],
    *,
    debug: bool = False,
    span_groups: list[SpanGroup] | None = None,
) -> tuple[list[list[str]], int]:
    if not grid:
        return [], 0
    width = max(map(len, grid))
    rows = [row + [""] * (width - len(row)) for row in grid]
    header_count, first_numeric_row = 1, len(rows)
    for i, row in enumerate(rows):
        values = [cell.strip() for cell in row if cell.strip()]
        numeric = sum(
            is_numeric_cell(cell) and not YEAR_TOKEN_RE.match(cell) for cell in values
        )
        if values and numeric / len(values) >= 0.25:
            header_count = first_numeric_row = i
            break

    # Keep sparse section rows in the body after a multi-column header.
    for i in range(1, min(first_numeric_row, len(rows) - 1)):
        values = [cell.strip() for cell in rows[i] if cell.strip()]
        next_values = [cell.strip() for cell in rows[i + 1] if cell.strip()]
        previous_values = [cell.strip() for cell in rows[i - 1] if cell.strip()]
        if len(values) <= 1 and len(next_values) <= 1 and len(previous_values) > 1:
            header_count = i
            break
        if (
            len(values) <= 1
            and len(previous_values) > 1
            and any(is_numeric_cell(value) for value in next_values)
        ):
            header_count = i
            break

    kept = apply_grid_repairs(rows, header_count, debug=debug, span_groups=span_groups)
    healed = [
        [
            NUMERIC_PERCENT_SPACE_RE.sub(
                r"\1%", PAREN_SPACES_RE.sub(r"(\1)", rows[r][c].strip())
            )
            for c in kept
        ]
        for r in range(len(rows))
    ]
    if debug:
        print(
            f"[table-debug] first_numeric_row={first_numeric_row} "
            f"selected header_count={header_count}",
            file=sys.stderr,
        )
        for index, row in enumerate(healed):
            print(
                f"[table-debug] healed "
                f"{'header' if index < header_count else 'data'} row {index}: {row!r}",
                file=sys.stderr,
            )
    return healed, header_count


def convert_html_tables_to_ascii(html_content: str, *, debug: bool = False) -> str:
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

    for table_index, table in enumerate(list(soup.find_all("table"))):
        rows = table.find_all("tr")
        if len(rows) <= 1:
            table.unwrap()
            continue
        cells = table.find_all(["td", "th"])
        full_text = table.get_text(" ", strip=True)
        signature_output = _signature_template(table)
        if signature_output:
            table.replace_with(soup.new_string(signature_output))
            continue
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
        is_toc = (
            "item" in full_text.lower()
            and "page" in full_text.lower()
            and "part i" in full_text.lower()
        )
        non_empty = [_cell_text(cell) for cell in cells if _cell_text(cell)]
        numeric = sum(is_numeric_cell(cell) for cell in non_empty)
        source_grid, span_groups = _span_grid(table, with_spans=True)
        registration_output = _registration_table_template(source_grid)
        if registration_output:
            table.replace_with(soup.new_string(registration_output))
            continue
        if (
            len(rows) < 3
            or not non_empty
            or (not is_toc and numeric / len(non_empty) < 0.15)
        ):
            table.unwrap()
            continue
        if debug:
            print(
                f"[table-debug] table {table_index}: source grid "
                f"{len(source_grid)}x{max(map(len, source_grid), default=0)}",
                file=sys.stderr,
            )
            for index, row in enumerate(source_grid):
                print(f"[table-debug] source row {index}: {row!r}", file=sys.stderr)
            for row, start, end, label in span_groups:
                print(
                    f"[table-debug] span row {row}: columns {start}:{end} "
                    f"label={label!r}",
                    file=sys.stderr,
                )
        grid, header_count = _heal_grid(
            source_grid, debug=debug, span_groups=span_groups
        )
        if not grid or len(grid[0]) <= 1:
            table.unwrap()
            continue
        converted = (
            HTMLTableConverter(grid=grid, header_row_count=header_count)
            .to_generic_table()
            .build()
        )
        if debug:
            print(
                f"[table-debug] table {table_index}: converted output", file=sys.stderr
            )
            print(converted, file=sys.stderr)
        table.replace_with(soup.new_string(converted))
    return soup.get_text(separator="\n")


__all__ = ["GenericTable", "HTMLTableConverter", "convert_html_tables_to_ascii"]
