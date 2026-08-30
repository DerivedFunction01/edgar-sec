"""Condition-aware column repairs for HTML table grids."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass

from .patterns import FOOTNOTE_RE, YEAR_IN_HEADER_RE, YEAR_TOKEN_RE
from .tokens import PREFIX_SYMBOLS, PREFIX_TOKENS, SUFFIX_TOKENS, is_numeric_cell

SpanGroup = tuple[int, int, int, str]
TemplateMatcher = Callable[[list[list[str]], int, list[SpanGroup]], list[SpanGroup]]


@dataclass(frozen=True)
class GridTemplate:
    name: str
    match: TemplateMatcher
    apply: Callable[[list[list[str]], int, set[int], list[SpanGroup]], None]


GridRepair = Callable[[list[list[str]], int, set[int]], None]


def _is_section(row: list[str]) -> bool:
    cells = [cell.strip().lower() for cell in row if cell.strip()]
    return bool(cells) and all(not is_numeric_cell(cell) for cell in cells)


def _collapse_span_groups(
    rows: list[list[str]],
    header_count: int,
    drop: set[int],
    span_groups: list[SpanGroup],
) -> None:
    for row, start, end, label in span_groups:
        if row >= header_count or end - start != 3:
            continue
        if not any(
            any(
                (value in PREFIX_SYMBOLS or value in PREFIX_TOKENS)
                and is_numeric_cell(values[index + 1])
                for index, value in enumerate(values[:-1])
            )
            for body_row in rows[header_count:]
            for values in [[body_row[column].strip() for column in range(start, end)]]
        ):
            continue
        for body_row in range(header_count, len(rows)):
            values = [rows[body_row][column].strip() for column in range(start, end)]
            non_empty = [value for value in values if value]
            if not non_empty:
                continue
            merged = "".join(non_empty)
            rows[body_row][start] = merged
            for column in range(start + 1, end):
                rows[body_row][column] = ""
        drop.update(range(start + 1, end))


def _match_year_value_groups(
    rows: list[list[str]], header_count: int, span_groups: list[SpanGroup]
) -> list[SpanGroup]:
    matches = []
    for row, start, end, label in span_groups:
        if row >= header_count or end - start != 3:
            continue
        if not (YEAR_TOKEN_RE.match(label) or YEAR_IN_HEADER_RE.search(label)):
            continue
        if any(
            any(
                (value in PREFIX_SYMBOLS or value in PREFIX_TOKENS)
                and is_numeric_cell(values[index + 1])
                for index, value in enumerate(values[:-1])
            )
            for values in (
                [rows[body_row][column].strip() for column in range(start, end)]
                for body_row in range(header_count, len(rows))
            )
        ):
            matches.append((row, start, end, label))
    return matches


def _match_repeated_value_groups(
    rows: list[list[str]], header_count: int, span_groups: list[SpanGroup]
) -> list[SpanGroup]:
    candidates = []
    for group in span_groups:
        row, start, end, label = group
        if row >= header_count or end - start != 3 or not label.strip():
            continue
        if YEAR_TOKEN_RE.match(label) or YEAR_IN_HEADER_RE.search(label):
            continue
        if any(
            any(
                (value in PREFIX_SYMBOLS or value in PREFIX_TOKENS)
                and is_numeric_cell(values[index + 1])
                for index, value in enumerate(values[:-1])
            )
            for body_row in range(header_count, len(rows))
            for values in [
                [rows[body_row][column].strip() for column in range(start, end)]
            ]
        ):
            candidates.append(group)
    return candidates if len(candidates) >= 2 else []


def _match_headerless_maturity_groups(
    rows: list[list[str]], header_count: int, span_groups: list[SpanGroup]
) -> list[SpanGroup]:
    matches = [
        group
        for group in span_groups
        if group[0] >= header_count
        and group[1] == 0
        and group[2] - group[1] == 3
        and YEAR_TOKEN_RE.match(group[3])
    ]
    return matches if len(matches) >= 2 else []


def _collapse_headerless_maturity_groups(
    rows: list[list[str]],
    header_count: int,
    drop: set[int],
    span_groups: list[SpanGroup],
) -> None:
    for body_row in range(header_count, len(rows)):
        if len(rows[body_row]) < 5:
            continue
        prefix = rows[body_row][3].strip()
        value = rows[body_row][4].strip()
        if prefix in PREFIX_SYMBOLS or prefix in PREFIX_TOKENS:
            if value:
                rows[body_row][3] = prefix + value
                rows[body_row][4] = ""
    drop.update({4, 5})


GRID_TEMPLATES = (
    GridTemplate(
        "headerless_maturity_value_group",
        _match_headerless_maturity_groups,
        _collapse_headerless_maturity_groups,
    ),
    GridTemplate(
        "year_group_currency_value_spacer",
        _match_year_value_groups,
        _collapse_span_groups,
    ),
    GridTemplate(
        "repeated_value_group_currency_spacer",
        _match_repeated_value_groups,
        _collapse_span_groups,
    ),
)


def _drop_header_only_year_spacers(
    rows: list[list[str]], header_count: int, drop: set[int]
) -> None:
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
            if rows[row][column].strip() and not _is_section(rows[row])
        ]
        if (
            header_values
            and not body_values
            and any(YEAR_TOKEN_RE.match(value) for value in header_values)
        ):
            drop.add(column)


def _drop_footnote_columns(
    rows: list[list[str]], header_count: int, drop: set[int]
) -> None:
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
            if rows[row][column].strip() and not _is_section(rows[row])
        ]
        if not (
            cells
            and len(cells) <= (len(rows) - header_count) * 0.6
            and all(FOOTNOTE_RE.match(cell) for cell in cells)
        ):
            continue
        for row in range(header_count, len(rows)):
            if rows[row][column].strip() and not _is_section(rows[row]):
                for left in range(column - 1, -1, -1):
                    if rows[row][left].strip() and left not in drop:
                        rows[row][left] += " " + rows[row][column].strip()
                        break
        drop.add(column)


def _drop_suffix_columns(
    rows: list[list[str]], header_count: int, drop: set[int]
) -> None:
    width = max(map(len, rows), default=0)
    for column in range(1, width):
        if column in drop:
            continue
        cells = [
            rows[row][column].strip()
            for row in range(header_count, len(rows))
            if rows[row][column].strip() and not _is_section(rows[row])
        ]
        if not cells or not all(cell.casefold() in SUFFIX_TOKENS for cell in cells):
            continue
        for row in range(header_count, len(rows)):
            if rows[row][column].strip() and not _is_section(rows[row]):
                for left in range(column - 1, -1, -1):
                    if rows[row][left].strip() and left not in drop:
                        suffix = rows[row][column].strip()
                        rows[row][left] += (
                            "" if suffix.startswith(("%", ")")) else " "
                        ) + suffix
                        break
        drop.add(column)


def _merge_inline_suffix_cells(
    rows: list[list[str]], header_count: int, drop: set[int]
) -> None:
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


def _attach_inline_footnotes(
    rows: list[list[str]], header_count: int, drop: set[int]
) -> None:
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


def _drop_empty_body_columns(
    rows: list[list[str]], header_count: int, drop: set[int]
) -> None:
    width = max(map(len, rows), default=0)
    for column in range(1, width):
        if column in drop:
            continue
        if not any(row[column].strip() for row in rows):
            drop.add(column)


def _drop_prefix_columns(
    rows: list[list[str]], header_count: int, drop: set[int]
) -> None:
    width = max(map(len, rows), default=0)
    for column in range(width - 1):
        if column in drop:
            continue
        cells = [
            rows[row][column].strip()
            for row in range(header_count, len(rows))
            if rows[row][column].strip() and not _is_section(rows[row])
        ]
        if not cells or not all(
            cell in PREFIX_SYMBOLS or cell in PREFIX_TOKENS for cell in cells
        ):
            continue
        for row in range(header_count, len(rows)):
            if rows[row][column].strip() and not _is_section(rows[row]):
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


def _fold_dropped_headers(
    rows: list[list[str]], header_count: int, drop: set[int], kept: list[int]
) -> None:
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


def apply_grid_repairs(
    rows: list[list[str]],
    header_count: int,
    *,
    debug: bool,
    span_groups: list[SpanGroup] | None = None,
) -> list[int]:
    repairs: list[tuple[str, GridRepair]] = [
        ("drop_header_only_year_spacers", _drop_header_only_year_spacers),
        ("merge_inline_suffix_cells", _merge_inline_suffix_cells),
        ("drop_footnote_columns", _drop_footnote_columns),
        ("drop_suffix_columns", _drop_suffix_columns),
        ("drop_prefix_columns", _drop_prefix_columns),
    ]
    period_headers = [
        group
        for group in (span_groups or [])
        if group[0] < header_count
        and (YEAR_TOKEN_RE.match(group[3]) or YEAR_IN_HEADER_RE.search(group[3]))
    ]
    if len(period_headers) >= 2:
        repairs.extend(
            [
                ("attach_inline_footnotes", _attach_inline_footnotes),
                ("drop_empty_body_columns", _drop_empty_body_columns),
            ]
        )
    drop: set[int] = set()
    if span_groups:
        for template in GRID_TEMPLATES:
            matches = template.match(rows, header_count, span_groups)
            if matches:
                template.apply(rows, header_count, drop, matches)
                if debug:
                    print(
                        f"[table-debug] matched template {template.name}: "
                        f"groups={len(matches)} dropped={sorted(drop)}",
                        file=sys.stderr,
                    )
    for name, repair in repairs:
        before = len(drop)
        repair(rows, header_count, drop)
        if debug and len(drop) != before:
            print(
                f"[table-debug] applied {name}: dropped {sorted(drop)}", file=sys.stderr
            )
    kept = [
        column
        for column in range(max(map(len, rows), default=0))
        if column not in drop and any(row[column].strip() for row in rows)
    ]
    _fold_dropped_headers(rows, header_count, drop, kept)
    return kept
