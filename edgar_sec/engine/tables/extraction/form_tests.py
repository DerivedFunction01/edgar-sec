"""Form-test stage: registry-declared arithmetic tests over one table.

Evaluated once per table between context assembly and the vocabulary
competition; passed tests feed both competitions as evidence.
"""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.admission_evidence import (
    EVALUATORS as ADMISSION_EVALUATORS,
)
from edgar_sec.engine.tables.extraction.aro_evidence import (
    evaluate_form_test_aro,
)
from edgar_sec.engine.tables.extraction.composition import evaluate_composition
from edgar_sec.engine.tables.extraction.core_form_evidence import (
    evaluate_form_test_core_form,
)
from edgar_sec.engine.tables.extraction.derivatives_evidence import (
    evaluate_form_test_derivatives,
)
from edgar_sec.engine.tables.extraction.eps_evidence import (
    evaluate_form_test_eps,
    evaluate_form_test_eps_detector,
)
from edgar_sec.engine.tables.extraction.inventory_evidence import (
    evaluate_form_test_inventory,
)
from edgar_sec.engine.tables.extraction.labor_evidence import (
    evaluate_form_test_labor,
)
from edgar_sec.engine.tables.extraction.lease_evidence import (
    evaluate_form_test_lease,
)
from edgar_sec.engine.tables.extraction.stock_comp_evidence import (
    evaluate_form_test_stock_comp,
)
from edgar_sec.engine.tables.extraction.measure_set import evaluate_measure_set
from edgar_sec.engine.tables.extraction.normalize import normalize_text
from edgar_sec.engine.tables.extraction.percentage_form import (
    evaluate_percentage_form,
)
from edgar_sec.engine.tables.extraction.pension_routed_evidence import (
    evaluate_form_test_pension_routed,
)
from edgar_sec.engine.tables.extraction.ppe_evidence import (
    evaluate_form_test_ppe,
)
from edgar_sec.engine.tables.extraction.form_signal_specs import (
    ORIENT_EITHER_AXIS,
    PLACEMENT_SPECS_BY_TEST_ID,
    PRED_DEEP_NOTES,
    PRED_ISOLATED_DEEP_NOTES,
    PRED_NOTES_ISOLATED,
    ROW_BOUND_SPECS_BY_TEST_ID,
    SIGNATURE_ABSENCE_SPECS_BY_TEST_ID,
)
from edgar_sec.engine.tables.extraction.form_test_specs import (
    FORM_TEST_SPECS,
    WALK_SPECS_BY_TEST_ID,
    FormTestOutcome,
    FormTestSpec,
    WalkSpec,
)
from edgar_sec.engine.tables.extraction.placement import (
    REGION_NOTES,
    PlacementFacts,
)
from edgar_sec.engine.tables.extraction.profiles import (
    TEST_ARO_EVIDENCE,
    TEST_ADMISSION_EVIDENCE,
    TEST_BALANCE_SHEET_SEPARATOR,
    TEST_CASH_FLOW_SEPARATOR,
    TEST_COMBINED_OPERATIONS_SEPARATOR,
    TEST_COMPREHENSIVE_INCOME_SEPARATOR,
    TEST_COMPOSITION_TWIN,
    TEST_CORE_FORM,
    TEST_CREDIT_SEPARATOR,
    TEST_CREDIT_LOSSES_EVIDENCE,
    TEST_DERIVATIVES_EVIDENCE,
    TEST_EPS_DETECTOR,
    TEST_EPS_EVIDENCE,
    TEST_EQUITY_SEPARATOR,
    TEST_INVENTORY_EVIDENCE,
    TEST_LABOR_FORM,
    TEST_LADDER,
    TEST_LEASE_EVIDENCE,
    TEST_MEASURE_SET,
    TEST_PENSION_ROUTED,
    TEST_STOCK_COMP_EVIDENCE,
    TEST_STOCK_COMP_SEPARATOR,
    TEST_PERCENTAGE_FORM,
    TEST_PLACEMENT_CONSISTENCY,
    TEST_PPE_EVIDENCE,
    TEST_PRIMARY_STATEMENT_SEAT,
    TEST_RESTRUCTURING_EVIDENCE,
    TEST_ROW_BOUND,
    TEST_SIGNATURE_ABSENCE,
    TEST_TAX_EVIDENCE,
    TEST_WALK,
    TEST_WARRANTY_EVIDENCE,
)
from edgar_sec.engine.tables.extraction.restructuring_evidence import (
    evaluate_form_test_restructuring,
)
from edgar_sec.engine.tables.extraction.separator_form_tests import (
    _evaluate_balance_sheet_separator,
    _evaluate_cash_flow_separator,
    _evaluate_credit_separator,
    _evaluate_comprehensive_income_separator,
    _evaluate_combined_operations_separator,
    _evaluate_equity_separator,
    _evaluate_stock_comp_separator,
)
from edgar_sec.engine.tables.extraction.statement_seat import (
    evaluate_statement_seat,
)
from edgar_sec.engine.tables.extraction.credit_losses_evidence import (
    evaluate_form_test_credit_losses,
)
from edgar_sec.engine.tables.extraction.tax_evidence import evaluate_form_test_tax
from edgar_sec.engine.tables.extraction.typed_rows import RowKind, TypedTable
from edgar_sec.engine.tables.extraction.validation import values_close
from edgar_sec.engine.tables.extraction.warranty_evidence import (
    evaluate_form_test_warranty,
)
from edgar_sec.engine.tables.extraction.year_ladder import evaluate_form_test_ladder

_END_VALUE_WINDOW = 4


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
        if accepted and values_close(value, accepted_sum):
            continue
        accepted_sum += value
        accepted += 1
    return accepted >= 1 and values_close(begin + accepted_sum, end)


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


def _evaluate_derivatives(table: TypedTable, spec: FormTestSpec) -> FormTestOutcome:
    result = evaluate_form_test_derivatives(table, spec)
    return FormTestOutcome(
        spec.family,
        spec.test_id,
        spec.kind,
        result.admitted,
        True,
        0,
        spec.points,
        result.detail,
    )


def _evaluate_core_form(table: TypedTable, spec: FormTestSpec) -> FormTestOutcome:
    result = evaluate_form_test_core_form(table, spec)
    return FormTestOutcome(
        spec.family,
        spec.test_id,
        spec.kind,
        result.core_present,
        True,
        0,
        spec.points,
        result.detail,
    )


def _evaluate_pension_routed(table: TypedTable, spec: FormTestSpec) -> FormTestOutcome:
    result = evaluate_form_test_pension_routed(table, spec)
    return FormTestOutcome(
        spec.family,
        spec.test_id,
        spec.kind,
        result.admitted,
        True,
        0,
        spec.points,
        result.detail,
    )


def _evaluate_eps(table: TypedTable, spec: FormTestSpec) -> FormTestOutcome:
    result = evaluate_form_test_eps(table, spec)
    return FormTestOutcome(
        spec.family,
        spec.test_id,
        spec.kind,
        result.admitted,
        result.evaluable,
        0,
        spec.points,
        result.detail,
    )


def _evaluate_eps_detector(table: TypedTable, spec: FormTestSpec) -> FormTestOutcome:
    result = evaluate_form_test_eps_detector(table, spec)
    return FormTestOutcome(
        spec.family,
        spec.test_id,
        spec.kind,
        result.evaluable and not result.fired,
        result.evaluable,
        0,
        spec.points,
        result.detail,
    )


def _evaluate_ppe(table: TypedTable, spec: FormTestSpec) -> FormTestOutcome:
    result = evaluate_form_test_ppe(table, spec)
    return FormTestOutcome(
        spec.family,
        spec.test_id,
        spec.kind,
        result.admitted,
        result.evaluable,
        0,
        spec.points,
        result.detail,
    )


def _evaluate_restructuring(table: TypedTable, spec: FormTestSpec) -> FormTestOutcome:
    result = evaluate_form_test_restructuring(table, spec)
    return FormTestOutcome(
        spec.family,
        spec.test_id,
        spec.kind,
        result.admitted,
        True,
        0,
        spec.points,
        result.detail,
    )


def _evaluate_labor(table: TypedTable, spec: FormTestSpec) -> FormTestOutcome:
    result = evaluate_form_test_labor(table, spec)
    return FormTestOutcome(
        spec.family,
        spec.test_id,
        spec.kind,
        result.admitted,
        True,
        0,
        spec.points,
        result.detail,
    )


def _evaluate_tax(table: TypedTable, spec: FormTestSpec) -> FormTestOutcome:
    result = evaluate_form_test_tax(table, spec)
    return FormTestOutcome(
        spec.family,
        spec.test_id,
        spec.kind,
        result.admitted,
        True,
        0,
        spec.points,
        result.detail,
    )


def _evaluate_credit_losses(table: TypedTable, spec: FormTestSpec) -> FormTestOutcome:
    result = evaluate_form_test_credit_losses(table, spec)
    return FormTestOutcome(
        spec.family,
        spec.test_id,
        spec.kind,
        result.admitted,
        True,
        0,
        spec.points,
        result.detail,
    )


def _evaluate_aro(table: TypedTable, spec: FormTestSpec) -> FormTestOutcome:
    result = evaluate_form_test_aro(table, spec)
    return FormTestOutcome(
        spec.family,
        spec.test_id,
        spec.kind,
        result.admitted,
        True,
        0,
        spec.points,
        result.detail,
    )


def _evaluate_warranty(table: TypedTable, spec: FormTestSpec) -> FormTestOutcome:
    result = evaluate_form_test_warranty(table, spec)
    return FormTestOutcome(
        spec.family,
        spec.test_id,
        spec.kind,
        result.admitted,
        True,
        0,
        spec.points,
        result.detail,
    )


def _evaluate_inventory(table: TypedTable, spec: FormTestSpec) -> FormTestOutcome:
    result = evaluate_form_test_inventory(table, spec)
    return FormTestOutcome(
        spec.family,
        spec.test_id,
        spec.kind,
        result.admitted,
        result.evaluable,
        0,
        spec.points,
        result.detail,
    )


def _evaluate_stock_comp(table: TypedTable, spec: FormTestSpec) -> FormTestOutcome:
    result = evaluate_form_test_stock_comp(table, spec)
    return FormTestOutcome(
        spec.family,
        spec.test_id,
        spec.kind,
        result.admitted,
        result.evaluable,
        0,
        spec.points,
        result.detail,
    )


def _evaluate_lease(table: TypedTable, spec: FormTestSpec) -> FormTestOutcome:
    result = evaluate_form_test_lease(table, spec)
    return FormTestOutcome(
        spec.family,
        spec.test_id,
        spec.kind,
        result.admitted,
        result.evaluable,
        0,
        spec.points,
        result.detail,
    )


def _evaluate_admission(table: TypedTable, spec: FormTestSpec) -> FormTestOutcome:
    """Admission evidence: the priced core-signal read."""
    outcome = ADMISSION_EVALUATORS[spec.test_id](table)
    return FormTestOutcome(
        spec.family,
        spec.test_id,
        spec.kind,
        outcome.passed,
        outcome.evaluable,
        0,
        spec.points,
        outcome.detail,
    )


def _evaluate_measure_set(table: TypedTable, spec: FormTestSpec) -> FormTestOutcome:
    result = evaluate_measure_set(table, spec)
    return FormTestOutcome(
        spec.family,
        spec.test_id,
        spec.kind,
        result.admitted,
        result.evaluable,
        0,
        spec.points,
        result.detail,
    )


def _evaluate_row_bound(table: TypedTable, spec: FormTestSpec) -> FormTestOutcome:
    params = ROW_BOUND_SPECS_BY_TEST_ID[spec.test_id]
    grid_rows = table.context.grid_rows or len(table.rows)
    if grid_rows <= 0:
        return FormTestOutcome(
            spec.family,
            spec.test_id,
            spec.kind,
            False,
            False,
            0,
            spec.points,
            "no grid rows",
        )
    inside = params.min_rows <= grid_rows <= params.max_rows
    axis = "rows"
    if not inside and params.orientation == ORIENT_EITHER_AXIS:
        columns = table.context.max_row_cells or len(table.periods) + 1
        inside = params.min_rows <= columns <= params.max_rows
        axis = "columns" if inside else "rows"
    detail = (
        f"grid {axis} within [{params.min_rows}, {params.max_rows}]"
        if inside
        else f"grid rows {grid_rows} outside [{params.min_rows}, {params.max_rows}]"
    )
    return FormTestOutcome(
        spec.family,
        spec.test_id,
        spec.kind,
        inside,
        True,
        0,
        spec.points,
        detail,
    )


def _evaluate_absence(table: TypedTable, spec: FormTestSpec) -> FormTestOutcome:
    params = SIGNATURE_ABSENCE_SPECS_BY_TEST_ID[spec.test_id]
    labels = [normalize_text(row.label) for row in table.rows if row.label]
    if not labels:
        return FormTestOutcome(
            spec.family,
            spec.test_id,
            spec.kind,
            False,
            False,
            0,
            spec.points,
            "no labels",
        )
    signatures = [normalize_text(term) for term in params.signature_labels]
    present = next(
        (term for term in signatures if any(term in label for label in labels)),
        None,
    )
    detail = (
        f"signature label present: {present}"
        if present
        else "signature vocabulary wholly absent"
    )
    return FormTestOutcome(
        spec.family,
        spec.test_id,
        spec.kind,
        present is not None,
        True,
        0,
        spec.points,
        detail,
    )


def _placement_fired(predicate: str, facts: PlacementFacts) -> bool:
    if predicate == PRED_NOTES_ISOLATED:
        return facts.region == REGION_NOTES and facts.isolated
    if predicate == PRED_DEEP_NOTES:
        return facts.deep_notes
    if predicate == PRED_ISOLATED_DEEP_NOTES:
        return facts.isolated and facts.deep_notes
    return False


def _evaluate_placement(
    table: TypedTable, spec: FormTestSpec, facts: PlacementFacts | None
) -> FormTestOutcome:
    if facts is None:
        return FormTestOutcome(
            spec.family,
            spec.test_id,
            spec.kind,
            False,
            False,
            0,
            spec.points,
            "placement unstamped",
        )
    params = PLACEMENT_SPECS_BY_TEST_ID[spec.test_id]
    fired = _placement_fired(params.predicate, facts)
    detail = (
        f"placement conjunction {params.predicate} fired"
        if fired
        else f"placement conjunction {params.predicate} clear"
    )
    return FormTestOutcome(
        spec.family,
        spec.test_id,
        spec.kind,
        not fired,
        True,
        0,
        spec.points,
        detail,
    )


_EVALUATORS = {
    TEST_WALK: _evaluate_walk,
    TEST_LADDER: _evaluate_ladder,
    TEST_PERCENTAGE_FORM: _evaluate_percentage,
    TEST_PRIMARY_STATEMENT_SEAT: _evaluate_seat,
    TEST_COMPOSITION_TWIN: _evaluate_composition,
    TEST_DERIVATIVES_EVIDENCE: _evaluate_derivatives,
    TEST_CORE_FORM: _evaluate_core_form,
    TEST_BALANCE_SHEET_SEPARATOR: _evaluate_balance_sheet_separator,
    TEST_COMPREHENSIVE_INCOME_SEPARATOR: _evaluate_comprehensive_income_separator,
    TEST_PENSION_ROUTED: _evaluate_pension_routed,
    TEST_CASH_FLOW_SEPARATOR: _evaluate_cash_flow_separator,
    TEST_CREDIT_SEPARATOR: _evaluate_credit_separator,
    TEST_EQUITY_SEPARATOR: _evaluate_equity_separator,
    TEST_COMBINED_OPERATIONS_SEPARATOR: _evaluate_combined_operations_separator,
    TEST_STOCK_COMP_SEPARATOR: _evaluate_stock_comp_separator,
    TEST_EPS_EVIDENCE: _evaluate_eps,
    TEST_EPS_DETECTOR: _evaluate_eps_detector,
    TEST_PPE_EVIDENCE: _evaluate_ppe,
    TEST_RESTRUCTURING_EVIDENCE: _evaluate_restructuring,
    TEST_ARO_EVIDENCE: _evaluate_aro,
    TEST_WARRANTY_EVIDENCE: _evaluate_warranty,
    TEST_INVENTORY_EVIDENCE: _evaluate_inventory,
    TEST_LEASE_EVIDENCE: _evaluate_lease,
    TEST_TAX_EVIDENCE: _evaluate_tax,
    TEST_LABOR_FORM: _evaluate_labor,
    TEST_CREDIT_LOSSES_EVIDENCE: _evaluate_credit_losses,
    TEST_MEASURE_SET: _evaluate_measure_set,
    TEST_ADMISSION_EVIDENCE: _evaluate_admission,
    TEST_STOCK_COMP_EVIDENCE: _evaluate_stock_comp,
    TEST_ROW_BOUND: _evaluate_row_bound,
    TEST_SIGNATURE_ABSENCE: _evaluate_absence,
}


def evaluate_form_tests(
    table: TypedTable,
    specs: tuple[FormTestSpec, ...] = FORM_TEST_SPECS,
    placement: PlacementFacts | None = None,
) -> tuple[FormTestOutcome, ...]:
    """Evaluate every declared form test over one assembled table.
    Placement-kind tests need caller-stamped filing facts;
    unstamped they are unevaluable, never failed."""
    outcomes = []
    for spec in specs:
        if spec.kind == TEST_PLACEMENT_CONSISTENCY:
            outcomes.append(_evaluate_placement(table, spec, placement))
            continue
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
