"""Typed rows over a table context: caption parse, period binding, kinds."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from edgar_sec.engine.forms.common.numbers import clean_numeric
from edgar_sec.engine.tables.patterns import SCALE_PATTERNS
from edgar_sec.foundation.text.dates import (
    MONTH_PATTERN,
    YEAR_TOKEN_RE,
    YEAR_TOKEN_SEARCH_RE,
)

from .context import Scale, TableContext
from .normalize import collapse_text

_MAX_CAPTION_ROWS = 6
_MONTH_TOKEN_RE = re.compile(rf"\b(?:{MONTH_PATTERN})\b", re.IGNORECASE)
_PAREN_RE = re.compile(r"\([^)]*\)")
_TOTAL_RE = re.compile(r"^\s*total\b", re.IGNORECASE)
_PERIOD_HINTS = ("ended", "as of", "months", "weeks", "quarter", "fiscal")


def _scale_in(text: str) -> Scale | None:
    for pattern, unit in SCALE_PATTERNS:
        match = pattern.search(text)
        if match:
            return Scale(phrase=match.group(0).lower(), unit=unit)
    return None


def _has_period_evidence(text: str) -> bool:
    lower = text.lower()
    return (
        bool(YEAR_TOKEN_SEARCH_RE.search(text))
        or bool(_MONTH_TOKEN_RE.search(text))
        or any(hint in lower for hint in _PERIOD_HINTS)
    )


@dataclass(frozen=True, slots=True)
class CaptionInfo:
    """A caption stack parsed into company, titles, and stated facts."""

    lines: tuple[str, ...]
    company: str | None
    titles: tuple[str, ...]
    audit_status: str | None
    scale: Scale | None
    continued: bool
    consumed_rows: int


def parse_caption_stack(rows: tuple[tuple[str, ...], ...]) -> CaptionInfo:
    """Parse the leading single-cell rows of a grid as caption data."""
    lines: list[str] = []
    consumed = 0
    for row in rows:
        nonempty = [cell.strip() for cell in row if cell.strip()]
        if not nonempty:
            if not lines:
                consumed += 1
                continue
            break
        if len(nonempty) > 1 or len(lines) >= _MAX_CAPTION_ROWS:
            break
        lines.append(nonempty[0])
        consumed += 1

    company: str | None = None
    titles: list[str] = []
    audit_status: str | None = None
    scale: Scale | None = None
    continued = False
    for position, line in enumerate(lines):
        segments = _PAREN_RE.findall(line)
        remainder = collapse_text(_PAREN_RE.sub(" ", line))
        for segment in segments:
            lowered = segment.lower()
            if "unaudited" in lowered:
                audit_status = "unaudited"
            elif "audited" in lowered:
                audit_status = "audited"
            if "continued" in lowered:
                continued = True
            if scale is None:
                scale = _scale_in(segment)
        if scale is None:
            scale = _scale_in(remainder)
        if not remainder:
            continue
        if position == 0 and len(lines) > 1:
            company = remainder
        else:
            titles.append(remainder)
    return CaptionInfo(
        lines=tuple(lines),
        company=company,
        titles=tuple(titles),
        audit_status=audit_status,
        scale=scale,
        continued=continued,
        consumed_rows=consumed,
    )


@dataclass(frozen=True, slots=True)
class ColumnPeriod:
    """The period bound to one value column; label None is unknown."""

    column: int
    group: str | None
    date_text: str | None
    label: str | None


def _compose_label(group: str | None, date_text: str | None) -> str | None:
    if date_text is None:
        return group
    if group is None:
        return date_text
    head = group.rstrip(", ").strip()
    if YEAR_TOKEN_RE.fullmatch(date_text):
        if _MONTH_TOKEN_RE.search(head):
            return f"{head}, {date_text}"
        return f"{head} {date_text}"
    return f"{head} {date_text}"


class RowKind(Enum):
    """The structural kind of one typed row."""

    SECTION = "section"
    SUBTOTAL = "subtotal"
    TOTAL = "total"
    PARENTHETICAL = "parenthetical"
    DATA = "data"


@dataclass(frozen=True, slots=True)
class TypedRow:
    """One body row: label, per-column values, and structural kind."""

    label: str
    values: tuple[float | int | None, ...]
    kind: RowKind
    raw: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TypedTable:
    """A context structured: parsed caption, bound periods, typed rows."""

    context: TableContext
    caption: CaptionInfo
    periods: tuple[ColumnPeriod, ...]
    rows: tuple[TypedRow, ...]
    scale: Scale | None
    header_rows: int
    continued: bool


def _candidate_columns(
    rows: tuple[tuple[str, ...], ...], start: int, width: int
) -> tuple[int, ...]:
    columns = []
    for column in range(1, width):
        if any(
            column < len(row) and clean_numeric(row[column]) is not None
            for row in rows[start:]
        ):
            columns.append(column)
    return tuple(columns)


def _column_clusters(
    rows: tuple[tuple[str, ...], ...],
    candidates: tuple[int, ...],
    span_starts: frozenset[int],
) -> tuple[tuple[int, ...], ...]:
    clusters: list[list[int]] = []
    for column in candidates:
        if clusters and column == clusters[-1][-1] + 1 and column not in span_starts:
            partner = clusters[-1][-1]
            exclusive = all(
                not (
                    partner < len(row)
                    and column < len(row)
                    and clean_numeric(row[partner]) is not None
                    and clean_numeric(row[column]) is not None
                )
                for row in rows
            )
            if exclusive:
                clusters[-1].append(column)
                continue
        clusters.append([column])
    return tuple(tuple(cluster) for cluster in clusters)


def _cluster_value(
    row: tuple[str, ...], cluster: tuple[int, ...]
) -> float | int | None:
    for column in cluster:
        if column < len(row):
            value = clean_numeric(row[column])
            if value is not None:
                return value
    return None


def _row_kind(label: str, values: tuple[float | int | None, ...]) -> RowKind:
    if not any(value is not None for value in values):
        if label.startswith("(") and label.endswith(")"):
            return RowKind.PARENTHETICAL
        return RowKind.SECTION if label else RowKind.DATA
    if _TOTAL_RE.match(label):
        return RowKind.TOTAL
    if "subtotal" in label.lower():
        return RowKind.SUBTOTAL
    return RowKind.DATA


def _caption_group(caption: CaptionInfo) -> str | None:
    for line in reversed(caption.lines):
        if _has_period_evidence(line) and not YEAR_TOKEN_SEARCH_RE.search(line):
            return line
    return None


def structure_table(context: TableContext) -> TypedTable:
    """Structure one context into a typed table; never re-parse text."""
    rows = context.rows
    width = max((len(row) for row in rows), default=0)
    caption = parse_caption_stack(rows)
    start = caption.consumed_rows
    candidates = _candidate_columns(rows, start, width)

    header_cells: list[tuple[int, int, int, str]] = []
    continued = caption.continued
    cursor = start
    while cursor < len(rows):
        row = rows[cursor]
        cells = [collapse_text(cell) for cell in row]
        if not any(cells):
            cursor += 1
            continue
        if any(_has_period_evidence(cell) for cell in cells if cell):
            if cells and "(continued)" in cells[0].lower():
                continued = True
            for column, cell in enumerate(cells):
                if cell and _has_period_evidence(cell):
                    span_end = next(
                        (
                            later
                            for later in range(column + 1, len(cells))
                            if cells[later]
                        ),
                        width,
                    )
                    header_cells.append((cursor, column, span_end, cell))
            cursor += 1
            continue
        if any(
            column < len(row) and clean_numeric(row[column]) is not None
            for column in candidates
        ):
            break
        if cells[0]:
            if "(continued)" in cells[0].lower():
                continued = True
                cursor += 1
                continue
            break
        cursor += 1
    header_rows = cursor - start

    zone_scale: Scale | None = None
    for row in rows[start:cursor]:
        for cell in row:
            if zone_scale is None:
                zone_scale = _scale_in(cell)
        if zone_scale is not None:
            break

    span_starts = frozenset(
        cell[1] for cell in header_cells if YEAR_TOKEN_SEARCH_RE.search(cell[3])
    )
    clusters = _column_clusters(rows[cursor:], candidates, span_starts)
    caption_group = _caption_group(caption)
    periods: list[ColumnPeriod] = []
    for cluster in clusters:
        covering = [
            cell
            for cell in header_cells
            if any(cell[1] <= column < cell[2] for column in cluster)
        ]
        dated = [cell for cell in covering if YEAR_TOKEN_SEARCH_RE.search(cell[3])]
        if dated:
            chosen = dated[-1]
            group = " ".join(cell[3] for cell in covering if cell[0] < chosen[0]).strip(
                " ,"
            )
            if not group and caption_group and YEAR_TOKEN_RE.fullmatch(chosen[3]):
                group = caption_group.strip(" ,")
            periods.append(
                ColumnPeriod(
                    column=cluster[-1],
                    group=group or None,
                    date_text=chosen[3],
                    label=_compose_label(group or None, chosen[3]),
                )
            )
        elif covering:
            text = covering[-1][3]
            periods.append(
                ColumnPeriod(column=cluster[-1], group=None, date_text=text, label=text)
            )
        else:
            periods.append(
                ColumnPeriod(column=cluster[-1], group=None, date_text=None, label=None)
            )

    typed_rows: list[TypedRow] = []
    for row in rows[cursor:]:
        if not any(cell.strip() for cell in row):
            continue
        label = collapse_text(row[0]) if row else ""
        values = tuple(_cluster_value(row, cluster) for cluster in clusters)
        typed_rows.append(
            TypedRow(
                label=label,
                values=values,
                kind=_row_kind(label, values),
                raw=tuple(row),
            )
        )

    return TypedTable(
        context=context,
        caption=caption,
        periods=tuple(periods),
        rows=tuple(typed_rows),
        scale=caption.scale or zone_scale or context.scale,
        header_rows=header_rows,
        continued=continued,
    )
