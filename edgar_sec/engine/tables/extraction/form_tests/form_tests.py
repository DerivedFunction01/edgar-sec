"""Form-test stage: registry-declared arithmetic tests over one table.

Evaluated once per table between context assembly and the vocabulary
competition; passed tests feed both competitions as evidence.
"""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.evidence.form.admission_evidence import (
    EVALUATORS as ADMISSION_EVALUATORS,
)
from edgar_sec.engine.tables.extraction.evidence.balance_sheet.aro_evidence import (
    evaluate_form_test_aro,
)
from edgar_sec.engine.tables.extraction.form_tests.composition import (
    evaluate_composition,
)
from edgar_sec.engine.tables.extraction.evidence.form.core_form_evidence import (
    evaluate_form_test_core_form,
)
from edgar_sec.engine.tables.extraction.evidence.balance_sheet.derivatives_evidence import (
    evaluate_form_test_derivatives,
)
from edgar_sec.engine.tables.extraction.evidence.equity.eps_evidence import (
    evaluate_form_test_eps,
    evaluate_form_test_eps_detector,
)
from edgar_sec.engine.tables.extraction.evidence.balance_sheet.inventory_evidence import (
    evaluate_form_test_inventory,
)
from edgar_sec.engine.tables.extraction.evidence.equity.eps_refusal_evidence import (
    evaluate_form_test_eps_adjacency_refusal,
    evaluate_form_test_eps_proforma_refusal,
)
from edgar_sec.engine.tables.extraction.evidence.form.labor_evidence import (
    evaluate_form_test_labor,
)
from edgar_sec.engine.tables.extraction.evidence.balance_sheet.lease_evidence import (
    evaluate_form_test_lease,
)
from edgar_sec.engine.tables.extraction.evidence.equity.stock_comp_evidence import (
    evaluate_form_test_stock_comp,
)
from edgar_sec.engine.tables.extraction.form_tests.measure_set import (
    evaluate_measure_set,
    group_presence,
)
from edgar_sec.engine.tables.extraction.form_tests.percentage_form import (
    evaluate_percentage_form,
)
from edgar_sec.engine.tables.extraction.pension.pension_combination_evidence import (
    evaluate_form_test_pension_combination,
)
from edgar_sec.engine.tables.extraction.pension.pension_routed_evidence import (
    evaluate_form_test_pension_routed,
)
from edgar_sec.engine.tables.extraction.evidence.balance_sheet.ppe_evidence import (
    evaluate_form_test_ppe,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_specs import (
    FORM_TEST_SPECS,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_types import (
    FormTestOutcome,
    FormTestSpec,
)
from edgar_sec.engine.tables.extraction.core.text.placement import PlacementFacts
from edgar_sec.engine.tables.extraction.core.subjects.profile_constants import (
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
    TEST_EPS_ADJACENCY_REFUSAL,
    TEST_EPS_PROFORMA_REFUSAL,
    TEST_EQUITY_SEPARATOR,
    TEST_FORM_SEPARATION,
    TEST_INVENTORY_EVIDENCE,
    TEST_LABOR_FORM,
    TEST_LADDER,
    TEST_LEASE_EVIDENCE,
    TEST_MEASURE_SET,
    TEST_PENSION_COMBINATION,
    TEST_PENSION_ROUTED,
    TEST_STOCK_COMP_EVIDENCE,
    TEST_STOCK_COMP_SEPARATOR,
    TEST_LEASE_SEPARATOR,
    TEST_RESTRUCTURING_SEPARATOR,
    TEST_PERCENTAGE_FORM,
    TEST_PLACEMENT_CONSISTENCY,
    TEST_PPE_EVIDENCE,
    TEST_PRIMARY_STATEMENT_SEAT,
    TEST_RESTRUCTURING_EVIDENCE,
    TEST_ROW_BOUND,
    TEST_SIGNATURE_ABSENCE,
    TEST_DEFERRED_TAX_SEPARATOR,
    TEST_TAX_EVIDENCE,
    TEST_TAX_RECONCILIATION_SEPARATOR,
    TEST_WALK,
    TEST_WARRANTY_EVIDENCE,
)
from edgar_sec.engine.tables.extraction.evidence.income_statement.restructuring_evidence import (
    evaluate_form_test_restructuring,
)
from edgar_sec.engine.tables.extraction.form_tests.separator_form_tests import (
    _evaluate_balance_sheet_separator,
    _evaluate_cash_flow_separator,
    _evaluate_credit_separator,
    _evaluate_comprehensive_income_separator,
    _evaluate_combined_operations_separator,
    _evaluate_deferred_tax_separator,
    _evaluate_equity_separator,
    _evaluate_restructuring_separator,
    _evaluate_stock_comp_separator,
    _evaluate_tax_reconciliation_separator,
    _evaluate_lease_separator,
    _evaluate_form_separation,
)
from edgar_sec.engine.tables.extraction.form_tests.signal_form_tests import (
    _evaluate_absence,
    _evaluate_placement,
    _evaluate_row_bound,
)
from edgar_sec.engine.tables.extraction.seats.statement_seat import (
    evaluate_statement_seat,
)
from edgar_sec.engine.tables.extraction.evidence.balance_sheet.credit_losses_evidence import (
    evaluate_form_test_credit_losses,
)
from edgar_sec.engine.tables.extraction.evidence.income_statement.tax_evidence import (
    evaluate_form_test_tax,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import TypedTable
from edgar_sec.engine.tables.extraction.form_tests.walk_form_tests import _evaluate_walk
from edgar_sec.engine.tables.extraction.evidence.balance_sheet.warranty_evidence import (
    evaluate_form_test_warranty,
)
from edgar_sec.engine.tables.extraction.form_tests.year_ladder import (
    evaluate_form_test_ladder,
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


def _evaluate_pension_combination(
    table: TypedTable, spec: FormTestSpec
) -> FormTestOutcome:
    result = evaluate_form_test_pension_combination(table, spec)
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


def _evaluate_eps_adjacency_refusal(
    table: TypedTable, spec: FormTestSpec
) -> FormTestOutcome:
    result = evaluate_form_test_eps_adjacency_refusal(table, spec)
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


def _evaluate_eps_proforma_refusal(
    table: TypedTable, spec: FormTestSpec
) -> FormTestOutcome:
    result = evaluate_form_test_eps_proforma_refusal(table, spec)
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
        group_presence(table, spec.test_id),
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
    TEST_PENSION_COMBINATION: _evaluate_pension_combination,
    TEST_CASH_FLOW_SEPARATOR: _evaluate_cash_flow_separator,
    TEST_CREDIT_SEPARATOR: _evaluate_credit_separator,
    TEST_EQUITY_SEPARATOR: _evaluate_equity_separator,
    TEST_COMBINED_OPERATIONS_SEPARATOR: _evaluate_combined_operations_separator,
    TEST_STOCK_COMP_SEPARATOR: _evaluate_stock_comp_separator,
    TEST_RESTRUCTURING_SEPARATOR: _evaluate_restructuring_separator,
    TEST_TAX_RECONCILIATION_SEPARATOR: _evaluate_tax_reconciliation_separator,
    TEST_DEFERRED_TAX_SEPARATOR: _evaluate_deferred_tax_separator,
    TEST_LEASE_SEPARATOR: _evaluate_lease_separator,
    TEST_FORM_SEPARATION: _evaluate_form_separation,
    TEST_EPS_EVIDENCE: _evaluate_eps,
    TEST_EPS_DETECTOR: _evaluate_eps_detector,
    TEST_EPS_ADJACENCY_REFUSAL: _evaluate_eps_adjacency_refusal,
    TEST_EPS_PROFORMA_REFUSAL: _evaluate_eps_proforma_refusal,
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
