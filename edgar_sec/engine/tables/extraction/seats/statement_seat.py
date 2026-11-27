"""Primary-statement seat evaluator for the form-test stage.

A statement form passes when the table sits in the statement
seat (body region, outside the TOC and closing spans) and the
spec's named identity closes over the table's own rows.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.core.text.normalize import normalize_text
from edgar_sec.engine.tables.extraction.form_specs.form_test_types import FormTestSpec
from edgar_sec.engine.tables.extraction.seats.specs.seat_test_specs import (
    SEAT_TEST_SPECS_BY_FAMILY,
    SeatTestSpec,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import RowKind, TypedTable
from edgar_sec.engine.tables.extraction.core.validation import evaluate_math

_BEGINNING_ANCHORS = (
    "beginning balance",
    "balance at beginning",
    "balance, beginning",
    "balance at january",
    "at beginning of period",
    "at beginning of year",
)
_ENDING_ANCHORS = (
    "ending balance",
    "balance at end",
    "balance, end",
    "balance at december",
    "at end of period",
    "at end of year",
)


@dataclass(frozen=True, slots=True)
class SeatResult:
    """One seat evaluation; the stage outcome's shape."""

    family: str
    test_id: str
    kind: str
    passed: bool
    evaluable: bool
    columns_closed: int
    points: float
    detail: str


def _close(params: SeatTestSpec, computed: float, target: float) -> bool:
    return abs(computed - target) <= max(
        params.tolerance_abs, params.tolerance_rel * abs(target)
    )


def _matches(label: str, anchors: tuple[str, ...]) -> bool:
    return any(anchor in label for anchor in anchors)


def _column_walk(table: TypedTable, params: SeatTestSpec) -> int:
    """Columns whose beginning plus movements reconcile to ending.

    Block-stacked statements are walked per segment: each
    beginning pairs with its first non-crossing ending anchor.
    """
    labels = [normalize_text(row.label) for row in table.rows]
    beginnings = [
        i for i, label in enumerate(labels) if _matches(label, _BEGINNING_ANCHORS)
    ]
    endings = [i for i, label in enumerate(labels) if _matches(label, _ENDING_ANCHORS)]
    if not beginnings or not endings:
        return 0
    best = 0
    for pos, begin_row in enumerate(beginnings):
        later = [e for e in endings if e > begin_row]
        if not later:
            continue
        end_row = later[0]
        next_begin = beginnings[pos + 1] if pos + 1 < len(beginnings) else None
        if next_begin is not None and end_row > next_begin:
            continue
        best = max(best, _walk_span(table, params, labels, begin_row, end_row))
    return best


def _walk_span(table, params, labels, begin_row, end_row) -> int:
    """The single-span walk over one beginning/ending pair."""
    movements = [
        index
        for index in range(begin_row + 1, end_row)
        if any(value is not None for value in table.rows[index].values)
        and table.rows[index].kind not in (RowKind.TOTAL, RowKind.SUBTOTAL)
        and not _matches(labels[index], _BEGINNING_ANCHORS)
        and not _matches(labels[index], _ENDING_ANCHORS)
    ]
    width = max((len(row.values) for row in table.rows), default=0)
    closed = 0
    for column in range(width):
        begin = table.rows[begin_row].values[column]
        end = table.rows[end_row].values[column]
        if begin is None or end is None:
            continue
        total = begin + sum(
            table.rows[index].values[column]
            for index in movements
            if column < len(table.rows[index].values)
            and table.rows[index].values[column] is not None
        )
        if _close(params, total, end):
            closed += 1
    if closed and width >= 2:
        ending_values = table.rows[end_row].values
        if all(value is not None for value in ending_values):
            if not _close(params, sum(ending_values[:-1]), ending_values[-1]):
                closed = 0
    return closed


def _identity_closes(table: TypedTable, family: str, params: SeatTestSpec) -> bool:
    if params.identity == "equity_column_walk":
        return _column_walk(table, params) >= 1
    outcomes = [o for o in evaluate_math(table) if o.family == family]
    named = [o for o in outcomes if o.identity == params.identity]
    return any(o.closed for o in (named or outcomes))


def evaluate_statement_seat(table: TypedTable, spec: FormTestSpec) -> SeatResult:
    """Evaluate one table against one primary-statement seat spec."""
    params = SEAT_TEST_SPECS_BY_FAMILY.get(spec.family)
    if params is None:
        return SeatResult(
            spec.family,
            spec.test_id,
            spec.kind,
            False,
            False,
            0,
            spec.points,
            "no seat parameters for family",
        )
    context = table.context
    seated = (
        context.region == params.seat_region
        and context.in_toc_span == params.in_toc_span
        and context.in_closing_span == params.in_closing_span
    )
    if not seated:
        return SeatResult(
            spec.family,
            spec.test_id,
            spec.kind,
            False,
            True,
            0,
            spec.points,
            "outside the statement seat",
        )
    closed = _identity_closes(table, spec.family, params)
    return SeatResult(
        spec.family,
        spec.test_id,
        spec.kind,
        closed,
        True,
        1 if closed else 0,
        spec.points,
        f"identity {params.identity} closed"
        if closed
        else f"identity {params.identity} open",
    )
