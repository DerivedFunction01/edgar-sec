"""Presentation table templates: bullet lists, signatures, side-by-side, and uniform text."""

from __future__ import annotations

import re
import textwrap

from defs.tables.builder import HTMLTableConverter
from defs.tables.currencies import PREFIX_SYMBOLS
from defs.tables.patterns import BULLET_MARKER_RE, UNITS_LABEL_RE
from defs.tables.tokens import is_numeric_cell
from defs.text.checkmarks import CHECKED_TOKENS, UNCHECKED_TOKENS
from defs.text.dates import YEAR_TOKEN_RE, parse_date

from .common import cell_lines, cell_text
from .exhibit_index import exhibit_index_template
from .signatures import signature_template as _signature_block_template


def titled_period_table_template(source_grid: list[list[str]]) -> str | None:
    """Move full-width title/unit rows out of a two-level period header."""
    compact = [[cell.strip() for cell in row if cell.strip()] for row in source_grid]
    if len(compact) < 5 or len(compact[0]) != 1 or len(compact[1]) != 1:
        return None
    if not UNITS_LABEL_RE.fullmatch(compact[1][0]):
        return None

    period_row = compact[2]
    date_row = compact[3]
    body = compact[4:]
    if len(period_row) != 1 or len(date_row) < 3 or not body:
        return None
    if not any(
        parse_date(cell) is not None or YEAR_TOKEN_RE.fullmatch(cell)
        for cell in date_row[1:]
    ):
        return None
    normalized_body = []
    for row in body:
        normalized = []
        index = 0
        while index < len(row):
            if row[index] in PREFIX_SYMBOLS and index + 1 < len(row):
                normalized.append(row[index] + row[index + 1])
                index += 2
            else:
                normalized.append(row[index])
                index += 1
        normalized_body.append(normalized)
    if any(len(row) != len(date_row) for row in normalized_body):
        return None

    # Keep the period group as a second header line while making the row
    # label and date columns the actual leaf headers.
    headers = [["", period_row[0], ""], date_row]
    return (
        HTMLTableConverter(
            grid=[*headers, *normalized_body],
            header_row_count=2,
            title=f"{compact[0][0]}\n{compact[1][0]}",
        )
        .to_generic_table()
        .build()
    )


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


def footnote_template(table: object, source_grid: list[list[str]]) -> str | None:
    """Render symbol-marked footnote rows as horizontal prose lines."""
    marker_re = re.compile(r"^[*†‡§u]+$")
    rows = [
        [cell_text(cell) for cell in row.find_all(["td", "th"]) if cell_text(cell)]
        for row in table.find_all("tr")
        if row.get_text(" ", strip=True)
    ]
    if not rows or len(rows) != len(source_grid):
        return None
    if not all(
        len(row) == 2 and marker_re.fullmatch(row[0]) and row[1] for row in rows
    ):
        return None
    return "\n" + "\n".join(f"{marker} {text}" for marker, text in rows) + "\n"


def marked_list_template(source_grid: list[list[str]]) -> str | None:
    """Render spacer-column bullet or numbered lists as row-aware prose."""
    marker_re = re.compile(r"^(?:[•·▪◦‣⁃*+-]+|\(?\d+[.)]|[A-Za-z][.)])$")
    rendered_rows = []
    for row in source_grid:
        values = [value.strip() for value in row if value.strip()]
        if not values or len(values) % 2:
            return None
        pairs = []
        for index in range(0, len(values), 2):
            if not marker_re.fullmatch(values[index]):
                return None
            pairs.append(f"{values[index]} {values[index + 1]}")
        rendered_rows.append("  ".join(pairs))
    if len(rendered_rows) < 2:
        return None
    return "\n" + "\n".join(rendered_rows) + "\n"


def definition_table_template(source_grid: list[list[str]]) -> str | None:
    """Render stable two-column prose key/value tables as labeled rows."""
    compact = [[value.strip() for value in row if value.strip()] for row in source_grid]
    if len(compact) < 2 or any(len(row) != 2 for row in compact):
        return None
    labels = [row[0] for row in compact]
    values = [row[1] for row in compact]
    if any(len(label.split()) > 5 for label in labels):
        return None
    if any(re.fullmatch(r"(?:[*†‡§u]+|\(?\d+[.)])", label) for label in labels):
        return None
    header_words = {"description", "amount", "date", "year", "period", "total"}
    if any(label.casefold() in header_words for label in labels[:2]):
        return None
    numeric_values = sum(is_numeric_cell(value) for value in values)
    if numeric_values / len(values) > 0.4:
        return None
    label_width = max(map(len, labels))
    output = []
    for label, value in compact:
        wrapped = textwrap.wrap(
            value,
            width=max(20, 100 - label_width - 2),
            break_long_words=False,
            break_on_hyphens=False,
        ) or [""]
        output.append(f"{label.ljust(label_width)}: {wrapped[0]}")
        output.extend(f"{' ' * (label_width + 2)}{line}" for line in wrapped[1:])
    return "\n" + "\n".join(output) + "\n"


def signature_template(table: object) -> str | None:
    """Render executive/sign-off signature blocks (see templates.signatures)."""
    return _signature_block_template(table)


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
    marker_values = {
        token
        for token in CHECKED_TOKENS | UNCHECKED_TOKENS
        if token.strip() and token.strip() != "&nbsp;"
    }
    status_columns = [
        column
        for column in range(2, len(starts))
        if all(not row[column] or row[column] in marker_values for row in rows[1:])
    ]
    if len(status_columns) < 2:
        return None
    return HTMLTableConverter(grid=rows, header_row_count=1).to_generic_table().build()


def two_column_prose_template(source_grid: list[list[str]]) -> str | None:
    """Render a two-column prose table as a two-column ASCII table.

    Matches tables where ``span_grid`` produces exactly two populated columns
    (e.g., company-name + ownership-percentage lists separated by spacer
    columns). Fires after all other templates and before the prose-unwrap
    fallback, and only when the grid is genuinely two columns.
    """
    if len(source_grid) < 2:
        return None
    width = max(len(row) for row in source_grid)
    if width < 2:
        return None
    padded = [row + [""] * (width - len(row)) for row in source_grid]
    populated_cols = [c for c in range(width) if any(row[c].strip() for row in padded)]
    if len(populated_cols) != 2:
        return None
    compact = [[row[populated_cols[0]], row[populated_cols[1]]] for row in padded]
    populated = [row for row in compact if any(cell.strip() for cell in row)]
    if len(populated) < 2:
        return None
    both_filled = sum(1 for row in populated if row[0].strip() and row[1].strip())
    if both_filled / len(populated) < 0.75:
        return None
    all_cells = [cell for row in compact for cell in row if cell.strip()]
    if not all_cells:
        return None
    if sum(is_numeric_cell(cell) for cell in all_cells) / len(all_cells) > 0.15:
        return None
    left_words = [len(row[0].split()) for row in populated if row[0].strip()]
    right_words = [len(row[1].split()) for row in populated if row[1].strip()]
    if left_words and right_words:
        avg_left = sum(left_words) / len(left_words)
        avg_right = sum(right_words) / len(right_words)
        if avg_left > 0 and avg_right > 0:
            ratio = min(avg_left, avg_right) / max(avg_left, avg_right)
            if ratio < 0.15:
                return None
    return (
        HTMLTableConverter(grid=compact, header_row_count=0).to_generic_table().build()
    )


def linked_index_template(table: object, source_grid: list[list[str]]) -> str | None:
    """Render mixed prose and linked page-index rows without a table wrapper."""
    rows = [row for row in table.find_all("tr") if row.get_text(" ", strip=True)]
    if len(rows) < 5 or len(rows) != len(source_grid):
        return None
    linked_rows = []
    prose_rows = []
    for index, row in enumerate(rows):
        values = [
            cell_text(cell) for cell in row.find_all(["td", "th"]) if cell_text(cell)
        ]
        anchors = row.find_all("a")
        if len(anchors) >= 2 and len(values) >= 2:
            linked_rows.append(index)
        elif len(values) == 1 and values[0].endswith(":"):
            prose_rows.append(index)
    if len(linked_rows) < 3 or len(linked_rows) / len(rows) < 0.4 or not prose_rows:
        return None

    descriptions = []
    page_values = []
    rendered_rows = []
    for index, row in enumerate(rows):
        values = [
            cell_text(cell) for cell in row.find_all(["td", "th"]) if cell_text(cell)
        ]
        if index in linked_rows:
            descriptions.append(values[0])
            page_values.append(values[-1])
        elif values:
            rendered_rows.append((index, values[0]))
    description_width = min(max(map(len, descriptions), default=0), 88)
    page_width = max(map(len, page_values), default=0)
    output = []
    for index, row in enumerate(source_grid):
        values = [value.strip() for value in row if value.strip()]
        if not values:
            continue
        if index in linked_rows:
            description = values[0]
            page = values[-1]
            wrapped = textwrap.wrap(
                description,
                width=description_width,
                break_long_words=False,
                break_on_hyphens=False,
            ) or [""]
            output.append(
                f"{wrapped[0].ljust(description_width)}  {page.rjust(page_width)}"
            )
            output.extend(wrapped[1:])
        else:
            output.extend(
                textwrap.wrap(values[0], width=100, break_long_words=False) or [""]
            )
    return "\n" + "\n".join(output) + "\n"


__all__ = [
    "bullet_list_template",
    "definition_table_template",
    "exhibit_index_template",
    "footnote_template",
    "linked_index_template",
    "marked_list_template",
    "side_by_side_template",
    "signature_template",
    "sparse_status_matrix_template",
    "two_column_prose_template",
    "uniform_text_table_template",
]
