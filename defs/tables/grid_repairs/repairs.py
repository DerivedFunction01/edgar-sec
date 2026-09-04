"""Standard column, footnote, and suffix/prefix grid repair operations."""

from __future__ import annotations

import re

from ..patterns import FOOTNOTE_RE, YEAR_TOKEN_RE
from ..tokens import (
    PREFIX_SYMBOLS,
    PREFIX_TOKENS,
    SUFFIX_TOKENS,
    is_financial_placeholder,
    is_numeric_cell,
    is_numeric_start,
    is_range_marker,
)


def is_section(row: list[str]) -> bool:
    """Determine if a row represents a text-only section header rather than data."""
    cells = [cell.strip().lower() for cell in row if cell.strip()]
    return bool(cells) and all(
        not is_numeric_cell(cell) and not is_numeric_start(cell) for cell in cells
    )


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
        if (
            not cells
            or len(cells) > (len(rows) - header_count) * 0.6
            or not all(FOOTNOTE_RE.match(cell) for cell in cells)
            or any(re.search(r"\d{2,}", cell) for cell in cells)
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

    Only fires on sparse prefix cells within data columns. Dedicated prefix
    columns where all non-empty cells are prefix symbols are handled by
    drop_prefix_columns.
    """
    width = max(map(len, rows), default=0)
    for column in range(width - 1):
        if column in drop:
            continue
        body_cells = [
            rows[row][column].strip()
            for row in range(header_count, len(rows))
            if rows[row][column].strip()
        ]
        if not body_cells or all(cell in PREFIX_SYMBOLS for cell in body_cells):
            continue
        symbol_count = sum(1 for cell in body_cells if cell in PREFIX_SYMBOLS)
        if symbol_count == 0:
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


def merge_range_columns(
    rows: list[list[str]], header_count: int, drop: set[int]
) -> None:
    """Merge standalone range separator columns (–, -, to, etc.) and their bounds into Column L."""
    width = max(map(len, rows), default=0)
    for column in range(1, width - 1):
        if column in drop:
            continue
        body_cells = [
            rows[row][column].strip()
            for row in range(header_count, len(rows))
            if rows[row][column].strip()
        ]
        if not body_cells or not all(is_range_marker(cell) for cell in body_cells):
            continue
        left = next(
            (
                c
                for c in range(column - 1, -1, -1)
                if c not in drop
                and any(rows[r][c].strip() for r in range(header_count, len(rows)))
            ),
            None,
        )
        right = next(
            (
                c
                for c in range(column + 1, width)
                if c not in drop
                and any(rows[r][c].strip() for r in range(header_count, len(rows)))
            ),
            None,
        )
        if left is None or right is None:
            continue
        left_has_header = any(rows[r][left].strip() for r in range(header_count))
        right_has_header = any(rows[r][right].strip() for r in range(header_count))
        if left_has_header and right_has_header:
            left_hdr = " ".join(
                rows[r][left].strip()
                for r in range(header_count)
                if rows[r][left].strip()
            )
            right_hdr = " ".join(
                rows[r][right].strip()
                for r in range(header_count)
                if rows[r][right].strip()
            )
            if left_hdr and right_hdr and left_hdr != right_hdr:
                continue

        for row in range(header_count, len(rows)):
            marker = rows[row][column].strip()
            l_val = rows[row][left].strip()
            r_val = rows[row][right].strip()
            if is_range_marker(marker):
                if (
                    l_val
                    and r_val
                    and not is_financial_placeholder(l_val)
                    and not is_financial_placeholder(r_val)
                ):
                    rows[row][left] = f"{l_val} – {r_val}"
                    rows[row][column] = ""
                    rows[row][right] = ""
            elif not marker and not l_val and r_val:
                rows[row][left] = r_val
                rows[row][right] = ""

        drop.add(column)
        drop.add(right)


def shift_sparse_numeric_cells_left(
    rows: list[list[str]], header_count: int, drop: set[int]
) -> None:
    """Align a row-local numeric cell with a dominant adjacent numeric column.

    This handles HTML rows that omit a currency-prefix cell and consequently
    start one physical column later than their neighboring period rows.
    """
    width = max(map(len, rows), default=0)
    numeric_counts = [
        sum(
            is_numeric_cell(rows[row][column].strip())
            for row in range(header_count, len(rows))
            if column < len(rows[row])
        )
        for column in range(width)
    ]
    for row in range(header_count, len(rows)):
        numeric_columns = [
            column
            for column, cell in enumerate(rows[row])
            if is_numeric_cell(cell.strip()) and column not in drop
        ]
        for column in numeric_columns:
            target = next((c for c in range(column - 1, 0, -1) if c not in drop), None)
            if target is None or rows[row][target].strip():
                continue
            target_has_header = any(
                rows[r][target].strip() for r in range(header_count)
            )
            col_has_header = any(rows[r][column].strip() for r in range(header_count))
            if target_has_header and col_has_header:
                continue
            is_majority = (
                numeric_counts[target] >= 2
                and numeric_counts[target] >= 2 * numeric_counts[column]
            )
            is_complementary = numeric_counts[target] >= 1 and not any(
                rows[r][target].strip() and rows[r][column].strip()
                for r in range(header_count, len(rows))
            )
            if is_majority or is_complementary:
                rows[row][target] = rows[row][column]
                rows[row][column] = ""


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
    data_kept = [t for t in kept if t > 0]
    if not data_kept:
        data_kept = kept
    if not data_kept:
        return
    for column in sorted(drop):
        for row in range(header_count):
            if column >= len(rows[row]):
                continue
            label = rows[row][column].strip()
            if not label:
                continue
            destination = min(
                data_kept,
                key=lambda target: (
                    abs(target - column),
                    bool(rows[row][target].strip())
                    if target < len(rows[row])
                    else False,
                    target < column,
                ),
            )
            if destination is not None and destination < len(rows[row]):
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
