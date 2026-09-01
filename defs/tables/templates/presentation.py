"""Presentation table templates: bullet lists, signatures, side-by-side, and uniform text."""

from __future__ import annotations

import re

from defs.tables.builder import HTMLTableConverter
from defs.tables.patterns import BULLET_MARKER_RE
from defs.tables.tokens import is_numeric_cell

from .common import cell_lines, cell_text, span_grid


def bullet_list_template(table: object) -> str | None:
    """Render 2-column tables where column 1 contains bullet markers as bulleted lists."""
    rows = table.find_all("tr")
    if not rows:
        return None
    bullet_rows = []
    for row in rows:
        row_cells = row.find_all(["td", "th"])
        if len(row_cells) != 2:
            return None
        marker = cell_text(row_cells[0])
        if not BULLET_MARKER_RE.match(marker) or len(marker) > 6:
            return None
        bullet_rows.append(f"• {cell_text(row_cells[1])}")
    if bullet_rows:
        return "\n" + "\n".join(bullet_rows) + "\n"
    return None


def signature_template(table: object) -> str | None:
    """Render executive/sign-off signature blocks."""
    source_grid, _ = span_grid(table, with_spans=True)
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
                and any(
                    cell.casefold() in {"name", "signature"} for cell in row if cell
                )
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

    marker_positions = [
        (row_index, column)
        for row_index, row in enumerate(source_grid)
        for column, cell in enumerate(row)
        if "/s/" in cell
    ]
    if (
        len(marker_positions) >= 2
        and len({column for _, column in marker_positions}) >= 2
    ):
        midpoint = len(source_grid[0]) // 2
        rows = []
        for row in source_grid:
            left = " ".join(cell for cell in row[:midpoint] if cell).strip()
            right = " ".join(cell for cell in row[midpoint:] if cell).strip()
            if left or right:
                rows.append((left, right))
        width = max((len(left) for left, _ in rows), default=0)
        lines = [f"{left.ljust(width)}  {right}".rstrip() for left, right in rows]
        return "\n" + "\n".join(lines) + "\n"

    lines = [cell for row in source_grid for cell in row if cell]
    if len(marker_positions) == 1 and lines:
        rendered: list[str] = []
        for line in lines:
            if rendered and rendered[-1].casefold() in {"by", "by:"} and "/s/" in line:
                rendered[-1] = f"By: {line}"
            else:
                rendered.append(line)
        return "\n" + "\n".join(rendered) + "\n"

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


def side_by_side_template(table: object, source_grid: list[list[str]]) -> str | None:
    """Render two populated span groups as a horizontal presentation block."""
    if len(source_grid) < 2:
        return None
    populated_positions = [
        [index for index, cell in enumerate(row) if cell.strip()]
        for row in source_grid
        if any(cell.strip() for cell in row)
    ]
    if not populated_positions or any(
        positions[0] != 0 or positions[-1] < 6 for positions in populated_positions
    ):
        return None
    rows = table.find_all("tr")
    logical_rows: list[tuple[list[str], list[str]]] = []
    right_values: list[str] = []
    for row in rows:
        cells = row.find_all(["td", "th"])
        populated = [cell for cell in cells if cell_text(cell)]
        if not populated:
            continue
        if len(cells) < 3 or len(populated) != 2:
            return None
        right_values.append(cell_text(populated[-1]))
        logical_rows.append((cell_lines(populated[0]), cell_lines(populated[-1])))
    if not logical_rows:
        return None
    if sum(is_numeric_cell(value) for value in right_values) / len(right_values) > 0.5:
        return None

    width = min(max(len(" ".join(left)) for left, _ in logical_rows), 30)
    output: list[str] = []
    for left, right in logical_rows:
        line_count = max(len(left), len(right))
        for index in range(line_count):
            left_line = left[index] if index < len(left) else ""
            right_line = right[index] if index < len(right) else ""
            output.append(f"{left_line.ljust(width)}  {right_line}".rstrip())
    return "\n" + "\n".join(output) + "\n"


def uniform_text_table_template(source_grid: list[list[str]]) -> str | None:
    """Render a text-dominant table with a stable header and row shape."""
    if len(source_grid) < 3:
        return None
    compact = [[cell for cell in row if cell.strip()] for row in source_grid]
    width = len(compact[0])
    if width < 3 or any(len(row) != width for row in compact):
        return None
    if any(is_numeric_cell(cell) for cell in compact[0]):
        return None
    return (
        HTMLTableConverter(grid=compact, header_row_count=1).to_generic_table().build()
    )


def sparse_status_matrix_template(source_grid: list[list[str]]) -> str | None:
    """Render sparse marker matrices while preserving empty status columns."""
    if len(source_grid) < 2:
        return None
    starts = [index for index, cell in enumerate(source_grid[0]) if cell.strip()]
    if len(starts) < 4:
        return None
    groups = [
        (start, starts[index + 1] if index + 1 < len(starts) else len(source_grid[0]))
        for index, start in enumerate(starts)
    ]
    rows = [
        [
            " ".join(cell for cell in row[start:end] if cell).strip()
            for start, end in groups
        ]
        for row in source_grid
    ]
    if any(not row[0] or not row[1] for row in rows[1:]):
        return None
    marker_values = {"•", "✓", "✔", "☑", "☐", "x", "X"}
    status_columns = [
        column
        for column in range(2, len(starts))
        if all(not row[column] or row[column] in marker_values for row in rows[1:])
    ]
    if len(status_columns) < 2:
        return None
    return HTMLTableConverter(grid=rows, header_row_count=1).to_generic_table().build()


def exhibit_index_template(source_grid: list[list[str]]) -> str | None:
    """Render continuation rows from a two-column exhibit index as data."""
    if len(source_grid) < 4:
        return None
    compact = [[cell for cell in row if cell.strip()] for row in source_grid]
    if max((len(row) for row in compact), default=0) > 2:
        return None
    exhibit_re = re.compile(
        r"^\d+(?:\.\d+)?(?:\([a-z0-9]+\))?$|^\d{3}\*{2}$|^EX-\d+\.[A-Z]+$",
        re.IGNORECASE,
    )
    header_count = 0
    if compact and len(compact[0]) >= 2:
        first_cell = compact[0][0].casefold()
        second_cell = compact[0][1].casefold()
        if "exhibit" in first_cell and "description" in second_cell:
            header_count = 1
    exhibit_rows = compact[header_count:]
    if sum(bool(exhibit_re.fullmatch(row[0])) for row in exhibit_rows if row) < 3:
        return None
    rows = [row if len(row) == 2 else [row[0], ""] for row in compact]
    return (
        HTMLTableConverter(grid=rows, header_row_count=header_count)
        .to_generic_table()
        .build()
    )


__all__ = [
    "bullet_list_template",
    "exhibit_index_template",
    "side_by_side_template",
    "signature_template",
    "sparse_status_matrix_template",
    "uniform_text_table_template",
]
