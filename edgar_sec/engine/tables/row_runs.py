"""Generic geometric evidence for repeated ASCII table rows.
Repeated cell layout is recognized, not particular issuers or statement vocabulary; promotion
requires aligned columns and repeated numeric evidence across a bounded run.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from edgar_sec.engine.tables.numeric_cells import is_numeric_cell
from edgar_sec.foundation.text.dates import COLUMN_YEAR_ROW_RE, PERIOD_SUBHEADING_RE
from edgar_sec.foundation.text.patterns import (
    RE_COLUMN_GAP,
    RE_DOT_LEADER,
    RE_SENTENCE_TERMINAL,
    RE_SEPARATOR_LINE,
)

_MIN_ROWS = 3
_COLUMN_TOLERANCE = 4
_MAX_BLANK_GAP = 1
_MAX_HEADER_PREFIX_LINES = 2

Block = tuple[int, int, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class RowGeometry:
    """Layout summary of one nonblank line, with positions in source columns."""

    field_starts: tuple[int, ...]
    field_kinds: tuple[str, ...]
    numeric_fields: tuple[int, ...]
    numeric_value_fields: tuple[int, ...]
    prose_ending: bool


@dataclass(frozen=True, slots=True)
class TableRowRun:
    """A validated sequence of row blocks in the block-list coordinate frame."""

    first_block: int
    after_last_block: int
    start_line: int
    end_line: int
    row_count: int


def _field_kind(value: str) -> str:
    if is_numeric_cell(value):
        return "numeric"
    if any(char.isalpha() for char in value):
        return "alphabetic"
    return "other"


def measure_row(line: str) -> RowGeometry | None:
    """Measure cell starts and coarse field kinds for one line.
    Only internal whitespace runs of at least three characters split fields; leading indentation stays with the first field.
    """
    content_start = len(line) - len(line.lstrip())
    end = len(line.rstrip())
    if content_start >= end:
        return None

    fields: list[tuple[int, str]] = []
    field_start = content_start
    separators = sorted(
        (
            *RE_COLUMN_GAP.finditer(line, content_start, end),
            *RE_DOT_LEADER.finditer(line, content_start, end),
        ),
        key=lambda match: match.start(),
    )
    for match in separators:
        if len(match.group()) < 3 or match.start() < field_start:
            continue
        value = line[field_start : match.start()].strip()
        if value:
            fields.append((field_start, value))
        field_start = match.end()
        while field_start < end and line[field_start].isspace():
            field_start += 1

    value = line[field_start:end].strip()
    if value:
        fields.append((field_start, value))
    if len(fields) < 2:
        return None

    kinds = tuple(_field_kind(value) for _, value in fields)
    numeric_fields = tuple(
        index for index, kind in enumerate(kinds) if kind == "numeric"
    )
    numeric_value_fields = tuple(
        index
        for index, (_, value) in enumerate(fields)
        if is_numeric_cell(value) and any(char.isdigit() for char in value)
    )
    if not numeric_fields:
        return None
    return RowGeometry(
        field_starts=tuple(start for start, _ in fields),
        field_kinds=kinds,
        numeric_fields=numeric_fields,
        numeric_value_fields=numeric_value_fields,
        prose_ending=bool(
            RE_SENTENCE_TERMINAL.search(line) or line.rstrip().endswith((";", ":"))
        ),
    )


def _rows_share_structure(left: RowGeometry, right: RowGeometry) -> bool:
    left_anchors = left.field_starts[1:] + (
        (left.field_starts[0],) if 0 in left.numeric_fields else ()
    )
    right_anchors = right.field_starts[1:] + (
        (right.field_starts[0],) if 0 in right.numeric_fields else ()
    )
    return any(
        abs(left_start - right_start) <= _COLUMN_TOLERANCE
        for left_start in left_anchors
        for right_start in right_anchors
    )


def _run_has_prose_shape(rows: list[RowGeometry]) -> bool:
    return sum(row.prose_ending for row in rows) * 2 > len(rows)


def _has_repeated_numeric_values(rows: list[RowGeometry]) -> bool:
    return any(
        any(
            abs(left.field_starts[left_index] - right.field_starts[right_index])
            <= _COLUMN_TOLERANCE
            for left_index in left.numeric_value_fields
            for right_index in right.numeric_value_fields
        )
        for index, left in enumerate(rows)
        for right in rows[index + 1 :]
    )


def _measure_block_rows(lines: tuple[str, ...]) -> tuple[RowGeometry, ...]:
    nonblank = [line for line in lines if line.strip()]
    if not nonblank:
        return ()

    rows: list[RowGeometry] = []
    header_prefix_lines = 0
    for line in nonblank:
        stripped = line.strip()
        if (
            RE_SEPARATOR_LINE.fullmatch(stripped)
            or COLUMN_YEAR_ROW_RE.match(stripped)
            or PERIOD_SUBHEADING_RE.match(stripped)
        ):
            continue
        row = measure_row(line)
        if row is None:
            if not rows:
                if RE_SENTENCE_TERMINAL.search(line):
                    return ()
                header_prefix_lines += 1
                if header_prefix_lines > _MAX_HEADER_PREFIX_LINES:
                    return ()
                continue
            content_start = len(line) - len(line.lstrip())
            if (
                RE_SENTENCE_TERMINAL.search(line)
                or line.rstrip().endswith((";", ":"))
                or not any(
                    abs(content_start - start) <= _COLUMN_TOLERANCE
                    for start in rows[0].field_starts
                )
            ):
                return ()
            continue
        if rows and not _rows_share_structure(rows[0], row):
            return ()
        rows.append(row)
    return tuple(rows)


def is_data_row_candidate(lines: tuple[str, ...]) -> bool:
    """Return whether a block has a numeric multi-cell row shape.
    Stops fixed-width data rows being absorbed as headers merely because their cells are widely spaced.
    """
    return any(
        row.numeric_value_fields
        and row.numeric_value_fields[-1] < len(row.field_starts) - 1
        for row in _measure_block_rows(lines)
    )


def find_table_row_runs(
    blocks: list[Block],
    eligible_indices: set[int],
) -> tuple[TableRowRun, ...]:
    """Find bounded runs of at least three compatible numeric multi-cell rows.
    ``eligible_indices`` excludes blocks already known to be prose, protected, or structural.
    """
    measured: dict[int, tuple[RowGeometry, ...]] = {}
    for index in eligible_indices:
        if not 0 <= index < len(blocks):
            continue
        _, _, lines = blocks[index]
        rows = _measure_block_rows(lines)
        if rows:
            measured[index] = rows

    runs: list[TableRowRun] = []
    index = 0
    ordered = sorted(measured)
    while index < len(ordered):
        first = ordered[index]
        group = [first]
        reference = measured[first][0]
        row_geometries = list(measured[first])
        cursor = index + 1
        while cursor < len(ordered):
            previous = group[-1]
            candidate = ordered[cursor]
            gap = blocks[candidate][0] - blocks[previous][1]
            candidate_rows = measured[candidate]
            if gap > _MAX_BLANK_GAP or any(
                not _rows_share_structure(reference, row) for row in candidate_rows
            ):
                break
            group.append(candidate)
            row_geometries.extend(candidate_rows)
            cursor += 1

        if (
            len(row_geometries) >= _MIN_ROWS
            and _has_repeated_numeric_values(row_geometries)
            and not _run_has_prose_shape(row_geometries)
        ):
            runs.append(
                TableRowRun(
                    first_block=group[0],
                    after_last_block=group[-1] + 1,
                    start_line=blocks[group[0]][0],
                    end_line=blocks[group[-1]][1],
                    row_count=len(row_geometries),
                )
            )
            index += len(group)
        else:
            index += 1

    return tuple(runs)


def is_table_row_run_bridge(
    lines: tuple[str, ...],
    *,
    is_page_boundary_line: Callable[[str], bool] | None = None,
    is_table_bridge_line: Callable[[str], bool] | None = None,
) -> bool:
    """Accept only bounded structural, separator, or numeric rows between runs."""
    for line in lines:
        stripped = line.strip()
        if not stripped or RE_SEPARATOR_LINE.fullmatch(stripped):
            continue
        if (
            (is_page_boundary_line is not None and is_page_boundary_line(stripped))
            or (is_table_bridge_line is not None and is_table_bridge_line(stripped))
            or COLUMN_YEAR_ROW_RE.match(stripped)
            or PERIOD_SUBHEADING_RE.match(stripped)
        ):
            continue
        row = measure_row(line)
        if row is None or not row.numeric_value_fields or row.prose_ending:
            return False
    return True


__all__ = [
    "RowGeometry",
    "TableRowRun",
    "find_table_row_runs",
    "is_data_row_candidate",
    "is_table_row_run_bridge",
    "measure_row",
]
