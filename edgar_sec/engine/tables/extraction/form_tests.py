"""Form-test stage: registry-declared arithmetic tests over one table.

Evaluated once per table between context assembly and the vocabulary
competition; passed tests feed both competitions as evidence.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.composition import evaluate_composition
from edgar_sec.engine.tables.extraction.normalize import normalize_text
from edgar_sec.engine.tables.extraction.percentage_form import (
    evaluate_percentage_form,
)
from edgar_sec.engine.tables.extraction.form_test_specs import (
    FORM_TEST_SPECS,
    WALK_SPECS_BY_TEST_ID,
    FormTestSpec,
    WalkSpec,
)
from edgar_sec.engine.tables.extraction.profiles import (
    TEST_COMPOSITION_TWIN,
    TEST_LADDER,
    TEST_PERCENTAGE_FORM,
    TEST_PRIMARY_STATEMENT_SEAT,
    TEST_WALK,
)
from edgar_sec.engine.tables.extraction.statement_seat import (
    evaluate_statement_seat,
)
from edgar_sec.engine.tables.extraction.typed_rows import RowKind, TypedTable
from edgar_sec.engine.tables.extraction.year_ladder import evaluate_form_test_ladder

_ABS_TOLERANCE = 2.0
_REL_TOLERANCE = 0.005
_END_VALUE_WINDOW = 4

# Profile families whose cascade seat carries a shorter name.
CASCADE_FAMILY_ALIASES = {"aoci_rollforward": "aoci"}


def cascade_family(family: str) -> str:
    """The classify-cascade seat name for a profile family."""
    return CASCADE_FAMILY_ALIASES.get(family, family)


@dataclass(frozen=True, slots=True)
class FormTestOutcome:
    """One form test's evaluation over one table."""

    family: str
    test_id: str
    kind: str
    passed: bool
    evaluable: bool
    columns_closed: int
    points: float
    detail: str


# Closure tolerance is the Step 3 pricing tolerance, as in validation:
# max(2 units, 0.5% of the target), in the table's own stated units.
def _close(computed: float, target: float) -> bool:
    return abs(computed - target) <= max(_ABS_TOLERANCE, _REL_TOLERANCE * abs(target))


def _matches(label: str, patterns: tuple[str, ...]) -> bool:
    return any(pattern in label for pattern in patterns)


def _valued(table: TypedTable, index: int) -> bool:
    return any(value is not None for value in table.rows[index].values)


def _value_at(table: TypedTable, index: int, column: int) -> float | None:
    values = table.rows[index].values
    return (
        float(values[column])
        if column < len(values) and values[column] is not None
        else None
    )


def _first_valued(table: TypedTable, start: int, stop: int) -> int | None:
    for index in range(start, min(stop, len(table.rows))):
        if _valued(table, index):
            return index
    return None


def _columns(table: TypedTable, params: WalkSpec) -> tuple[int, ...]:
    if not params.column_headers:
        return tuple(range(max((len(row.values) for row in table.rows), default=0)))
    chosen = []
    for index, period in enumerate(table.periods):
        text = normalize_text(
            " ".join(
                part for part in (period.label, period.group, period.date_text) if part
            )
        )
        if _matches(text, params.column_headers):
            chosen.append(index)
    return tuple(chosen)


def _column_closes(
    table: TypedTable,
    begin_row: int,
    end_row: int,
    movements: list[int],
    column: int,
) -> bool:
    begin = _value_at(table, begin_row, column)
    end = _value_at(table, end_row, column)
    if begin is None or end is None:
        return False
    accepted_sum = 0.0
    accepted = 0
    for index in movements:
        value = _value_at(table, index, column)
        if value is None:
            continue
        if accepted and _close(value, accepted_sum):
            continue
        accepted_sum += value
        accepted += 1
    return accepted >= 1 and _close(begin + accepted_sum, end)


def _segment_closed(
    table: TypedTable,
    spec: FormTestSpec,
    params: WalkSpec,
    labels: list[str],
    begin_anchor: int,
    end_anchor: int,
    columns: tuple[int, ...],
) -> int:
    begin_row = _first_valued(table, begin_anchor, end_anchor)
    end_row = _first_valued(table, end_anchor, end_anchor + _END_VALUE_WINDOW)
    if begin_row is None or end_row is None or end_row <= begin_row:
        return 0
    movements = [
        index
        for index in range(begin_row + 1, end_row)
        if _valued(table, index)
        and table.rows[index].kind not in (RowKind.TOTAL, RowKind.SUBTOTAL)
        and not _matches(labels[index], spec.beginning)
        and not _matches(labels[index], spec.ending)
        and not _matches(labels[index], spec.excluded)
    ]
    if len(movements) < params.min_movements:
        return 0
    return sum(
        1
        for column in columns
        if _column_closes(table, begin_row, end_row, movements, column)
    )


def _evaluate_walk(table: TypedTable, spec: FormTestSpec) -> FormTestOutcome:
    """A walk: beginning plus movements reconciles to the ending."""
    labels = [normalize_text(row.label) for row in table.rows]
    beginnings = [
        i for i, label in enumerate(labels) if _matches(label, spec.beginning)
    ]
    endings = [i for i, label in enumerate(labels) if _matches(label, spec.ending)]
    if not beginnings or not endings:
        return FormTestOutcome(
            spec.family,
            spec.test_id,
            spec.kind,
            False,
            False,
            0,
            spec.points,
            "anchors absent",
        )
    params = WALK_SPECS_BY_TEST_ID.get(spec.test_id, WalkSpec())
    columns = _columns(table, params)
    if not columns:
        return FormTestOutcome(
            spec.family,
            spec.test_id,
            spec.kind,
            False,
            False,
            0,
            spec.points,
            "no participating column",
        )
    best = 0
    for begin_anchor in beginnings:
        for end_anchor in endings:
            if end_anchor <= begin_anchor:
                continue
            closed = _segment_closed(
                table, spec, params, labels, begin_anchor, end_anchor, columns
            )
            best = max(best, closed)
            if best >= params.min_columns:
                return FormTestOutcome(
                    spec.family,
                    spec.test_id,
                    spec.kind,
                    True,
                    True,
                    best,
                    spec.points,
                    f"walk closed in {best} column(s)",
                )
    return FormTestOutcome(
        spec.family,
        spec.test_id,
        spec.kind,
        False,
        True,
        best,
        spec.points,
        f"walk open in every segment (best {best} column(s))",
    )


def _evaluate_ladder(table: TypedTable, spec: FormTestSpec) -> FormTestOutcome:
    result = evaluate_form_test_ladder(table, spec)
    detail = f"ladder axis {result.axis or 'none'} ({result.kind or 'none'})"
    return FormTestOutcome(
        spec.family,
        spec.test_id,
        spec.kind,
        result.passed,
        True,
        len(result.steps),
        spec.points,
        detail,
    )


def _evaluate_percentage(table: TypedTable, spec: FormTestSpec) -> FormTestOutcome:
    result = evaluate_percentage_form(table, spec)
    return FormTestOutcome(
        result.family,
        result.test_id,
        result.kind,
        result.passed,
        result.evaluable,
        result.columns_closed,
        result.points,
        result.detail,
    )


def _evaluate_composition(table: TypedTable, spec: FormTestSpec) -> FormTestOutcome:
    result = evaluate_composition(table, spec)
    return FormTestOutcome(
        result.family,
        result.test_id,
        result.kind,
        result.passed,
        result.evaluable,
        result.columns_closed,
        result.points,
        result.detail,
    )


def _evaluate_seat(table: TypedTable, spec: FormTestSpec) -> FormTestOutcome:
    result = evaluate_statement_seat(table, spec)
    return FormTestOutcome(
        result.family,
        result.test_id,
        result.kind,
        result.passed,
        result.evaluable,
        result.columns_closed,
        result.points,
        result.detail,
    )


_EVALUATORS = {
    TEST_WALK: _evaluate_walk,
    TEST_LADDER: _evaluate_ladder,
    TEST_PERCENTAGE_FORM: _evaluate_percentage,
    TEST_PRIMARY_STATEMENT_SEAT: _evaluate_seat,
    TEST_COMPOSITION_TWIN: _evaluate_composition,
}


def evaluate_form_tests(
    table: TypedTable,
    specs: tuple[FormTestSpec, ...] = FORM_TEST_SPECS,
) -> tuple[FormTestOutcome, ...]:
    """Evaluate every declared form test over one assembled table."""
    outcomes = []
    for spec in specs:
        evaluator = _EVALUATORS.get(spec.kind)
        if evaluator is None:
            outcomes.append(
                FormTestOutcome(
                    spec.family,
                    spec.test_id,
                    spec.kind,
                    False,
                    False,
                    0,
                    spec.points,
                    "no evaluator for kind",
                )
            )
        else:
            outcomes.append(evaluator(table, spec))
    return tuple(outcomes)
