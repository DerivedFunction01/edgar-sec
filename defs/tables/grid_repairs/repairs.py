"""Standard column, footnote, and suffix/prefix grid repair operations."""

from __future__ import annotations

from ..patterns import FOOTNOTE_RE, YEAR_TOKEN_RE
from ..tokens import PREFIX_SYMBOLS, PREFIX_TOKENS, SUFFIX_TOKENS, is_numeric_cell


def is_section(row: list[str]) -> bool:
    """Determine if a row represents a text-only section header rather than data."""
    cells = [cell.strip().lower() for cell in row if cell.strip()]
    return bool(cells) and all(not is_numeric_cell(cell) for cell in cells)


def drop_header_only_year_spacers(
    rows: list[list[str]], header_count: int, drop: set[int]
) -> None:
    """Drop columns that only contain year tokens in the header and are empty in the body."""
    width = max(map(len, rows), default=0)
    for column in range(1, width):
        header_values = [
            rows[row][column].strip()
            for row in range(header_count)
            if rows[row][column].strip()
        ]
        body_values = [
            rows[row][column].strip()
            for row in range(header_count, len(rows))
            if rows[row][column].strip() and not is_section(rows[row])
        ]
        if (
            header_values
            and not body_values
            and any(YEAR_TOKEN_RE.match(value) for value in header_values)
        ):
            drop.add(column)


def drop_footnote_columns(
    rows: list[list[str]], header_count: int, drop: set[int]
) -> None:
    """Fold footnote-only columns into their adjacent left content cells and drop the column."""
    width = max(map(len, rows), default=0)
    change_header_columns = {
        column
        for row in rows[:header_count]
        for column, cell in enumerate(row)
        if "change" in cell.casefold()
    }
    for column in range(1, width):
        if column in drop or column in change_header_columns:
            continue
        cells = [
            rows[row][column].strip()
            for row in range(header_count, len(rows))
            if rows[row][column].strip() and not is_section(rows[row])
        ]
        if not (
            cells
            and len(cells) <= (len(rows) - header_count) * 0.6
            and all(FOOTNOTE_RE.match(cell) for cell in cells)
        ):
            continue
        for row in range(header_count, len(rows)):
            if rows[row][column].strip() and not is_section(rows[row]):
                for left in range(column - 1, -1, -1):
                    if rows[row][left].strip() and left not in drop:
                        rows[row][left] += " " + rows[row][column].strip()
                        break
        drop.add(column)


def drop_suffix_columns(
    rows: list[list[str]], header_count: int, drop: set[int]
) -> None:
    """Fold suffix-only columns into their left numeric neighbor and drop the column."""
    width = max(map(len, rows), default=0)
    for column in range(1, width):
        if column in drop:
            continue
        cells = [
            rows[row][column].strip()
            for row in range(header_count, len(rows))
            if rows[row][column].strip() and not is_section(rows[row])
        ]
        if not cells or not all(cell.casefold() in SUFFIX_TOKENS for cell in cells):
            continue
        for row in range(header_count, len(rows)):
            if rows[row][column].strip() and not is_section(rows[row]):
                for left in range(column - 1, -1, -1):
                    if rows[row][left].strip() and left not in drop:
                        suffix = rows[row][column].strip()
                        rows[row][left] += (
                            "" if suffix.startswith(("%", ")")) else " "
                        ) + suffix
                        break
        drop.add(column)


def merge_inline_suffix_cells(
    rows: list[list[str]], header_count: int, drop: set[int]
) -> None:
    """Merge standalone suffix tokens into preceding numeric cells on the same row."""
    width = max(map(len, rows), default=0)
    for column in range(1, width):
        if column in drop:
            continue
        for row in range(header_count, len(rows)):
            suffix = rows[row][column].strip()
            if suffix not in SUFFIX_TOKENS:
                continue
            previous_column = next(
                (
                    candidate
                    for candidate in range(column - 1, max(-1, column - 5), -1)
                    if rows[row][candidate].strip()
                ),
                None,
            )
            if previous_column is not None and is_numeric_cell(
                rows[row][previous_column]
            ):
                rows[row][previous_column] += suffix
                rows[row][column] = ""


def merge_prefix_columns(
    rows: list[list[str]], header_count: int, drop: set[int]
) -> None:
    """Merge standalone prefix symbols into the following numeric cell on the same row.

    Only fires on sparse prefix columns where the symbol appears in a minority
    of body rows. Consistent prefix columns (e.g. a dedicated currency column
    used on every row) are left intact.
    """
    width = max(map(len, rows), default=0)
    body_row_count = len(rows) - header_count
    for column in range(width - 1):
        if column in drop:
            continue
        body_cells = [
            rows[row][column].strip() for row in range(header_count, len(rows))
        ]
        symbol_count = sum(1 for cell in body_cells if cell in PREFIX_SYMBOLS)
        if symbol_count == 0 or (
            body_row_count > 1 and symbol_count / body_row_count > 0.5
        ):
            continue
        for row in range(header_count, len(rows)):
            prefix = rows[row][column].strip()
            if prefix not in PREFIX_SYMBOLS:
                continue
            next_column = next(
                (
                    candidate
                    for candidate in range(column + 1, width)
                    if rows[row][candidate].strip()
                ),
                None,
            )
            if next_column is not None and is_numeric_cell(rows[row][next_column]):
                rows[row][column] = prefix + rows[row][next_column].strip()
                rows[row][next_column] = ""


def attach_inline_footnotes(
    rows: list[list[str]], header_count: int, drop: set[int]
) -> None:
    """Attach footnote markers to preceding numeric values in period tables."""
    width = max(map(len, rows), default=0)
    for column in range(1, width):
        if column in drop:
            continue
        for row in range(header_count, len(rows)):
            footnote = rows[row][column].strip()
            parts = footnote.split()
            if not parts or not all(FOOTNOTE_RE.fullmatch(part) for part in parts):
                continue
            if all(part.strip("()†‡*§").isdigit() for part in parts):
                continue
            previous_column = next(
                (
                    candidate
                    for candidate in range(column - 1, max(-1, column - 5), -1)
                    if rows[row][candidate].strip()
                ),
                None,
            )
            if previous_column is not None and is_numeric_cell(
                rows[row][previous_column]
            ):
                rows[row][previous_column] += f" {footnote}"
                rows[row][column] = ""


def drop_empty_body_columns(
    rows: list[list[str]], header_count: int, drop: set[int]
) -> None:
    """Drop columns that have no text in any row."""
    width = max(map(len, rows), default=0)
    for column in range(1, width):
        if column in drop:
            continue
        if not any(row[column].strip() for row in rows[header_count:]):
            drop.add(column)


def drop_header_only_spacers(
    rows: list[list[str]], header_count: int, drop: set[int]
) -> None:
    """Drop empty body columns that sit between populated body columns."""
    width = max(map(len, rows), default=0)
    body_columns = {
        column
        for column in range(width)
        if any(rows[row][column].strip() for row in range(header_count, len(rows)))
    }
    if len(body_columns) < 2:
        return
    first_body, last_body = min(body_columns), max(body_columns)
    for column in range(first_body + 1, last_body):
        if column in body_columns or column in drop:
            continue
        drop.add(column)


def drop_prefix_columns(
    rows: list[list[str]], header_count: int, drop: set[int]
) -> None:
    """Fold currency/symbol prefix columns into their adjacent right neighbor."""
    width = max(map(len, rows), default=0)
    for column in range(width - 1):
        if column in drop:
            continue
        cells = [
            rows[row][column].strip()
            for row in range(header_count, len(rows))
            if rows[row][column].strip() and not is_section(rows[row])
        ]
        if not cells or not all(
            cell in PREFIX_SYMBOLS or cell in PREFIX_TOKENS for cell in cells
        ):
            continue
        for row in range(header_count, len(rows)):
            if rows[row][column].strip() and not is_section(rows[row]):
                for right in range(column + 1, width):
                    if rows[row][right].strip() and right not in drop:
                        prefix = rows[row][column].strip()
                        rows[row][right] = (
                            prefix
                            + ("" if prefix in PREFIX_SYMBOLS or prefix == "(" else " ")
                            + rows[row][right].strip()
                        )
                        break
        drop.add(column)


def fold_dropped_headers(
    rows: list[list[str]], header_count: int, drop: set[int], kept: list[int]
) -> None:
    """Preserve header labels from dropped columns into the closest remaining column."""
    for column in sorted(drop):
        for row in range(header_count):
            label = rows[row][column].strip()
            if not label:
                continue
            destination = next((target for target in kept if target > column), None)
            if destination is None:
                destination = next(
                    (target for target in reversed(kept) if target < column), None
                )
            if destination is not None:
                rows[row][destination] = " ".join(
                    part for part in (rows[row][destination].strip(), label) if part
                )


__all__ = [
    "attach_inline_footnotes",
    "drop_empty_body_columns",
    "drop_footnote_columns",
    "drop_header_only_spacers",
    "drop_header_only_year_spacers",
    "drop_prefix_columns",
    "drop_suffix_columns",
    "fold_dropped_headers",
    "is_section",
    "merge_inline_suffix_cells",
    "merge_prefix_columns",
]
