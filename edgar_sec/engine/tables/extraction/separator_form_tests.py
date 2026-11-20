"""Separator form-test evaluators: the separator kinds' stage adapters.

Each adapter runs its family's separator evidence over one table
and stamps the stage outcome (passed = the separator did not fire).
"""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.balance_sheet_separator_evidence import (
    evaluate_form_test_balance_sheet_separator,
)
from edgar_sec.engine.tables.extraction.cash_flow_separator_evidence import (
    evaluate_form_test_cash_flow_separator,
)
from edgar_sec.engine.tables.extraction.credit_separator_evidence import (
    evaluate_form_test_credit_separator,
)
from edgar_sec.engine.tables.extraction.combined_operations_separator_evidence import (
    evaluate_form_test_combined_operations_separator,
)
from edgar_sec.engine.tables.extraction.comprehensive_income_separator_evidence import (
    evaluate_form_test_comprehensive_income_separator,
)
from edgar_sec.engine.tables.extraction.equity_separator_evidence import (
    evaluate_form_test_equity_separator,
)
from edgar_sec.engine.tables.extraction.stock_comp_separator_evidence import (
    evaluate_form_test_stock_comp_separator,
)
from edgar_sec.engine.tables.extraction.tax_reconciliation_separator_evidence import (
    evaluate_form_test_tax_reconciliation_separator,
)
from edgar_sec.engine.tables.extraction.deferred_tax_separator_evidence import (
    evaluate_form_test_deferred_tax_separator,
)
from edgar_sec.engine.tables.extraction.lease_separator_evidence import (
    evaluate_form_test_lease_separator,
)
from edgar_sec.engine.tables.extraction.form_separation_evidence import (
    evaluate_form_test_form_separation,
)
from edgar_sec.engine.tables.extraction.form_test_specs import (
    FormTestOutcome,
    FormTestSpec,
)
from edgar_sec.engine.tables.extraction.typed_rows import TypedTable


def _evaluate_balance_sheet_separator(
    table: TypedTable, spec: FormTestSpec
) -> FormTestOutcome:
    result = evaluate_form_test_balance_sheet_separator(table, spec)
    return FormTestOutcome(
        spec.family,
        spec.test_id,
        spec.kind,
        not result.fired,
        result.evaluable,
        0,
        spec.points,
        result.detail,
    )


def _evaluate_cash_flow_separator(
    table: TypedTable, spec: FormTestSpec
) -> FormTestOutcome:
    result = evaluate_form_test_cash_flow_separator(table, spec)
    return FormTestOutcome(
        spec.family,
        spec.test_id,
        spec.kind,
        not result.fired,
        result.evaluable,
        0,
        spec.points,
        result.detail,
    )


def _evaluate_credit_separator(
    table: TypedTable, spec: FormTestSpec
) -> FormTestOutcome:
    result = evaluate_form_test_credit_separator(table, spec)
    return FormTestOutcome(
        spec.family,
        spec.test_id,
        spec.kind,
        not result.fired,
        result.evaluable,
        0,
        spec.points,
        result.detail,
    )


def _evaluate_combined_operations_separator(
    table: TypedTable, spec: FormTestSpec
) -> FormTestOutcome:
    result = evaluate_form_test_combined_operations_separator(table, spec)
    return FormTestOutcome(
        spec.family,
        spec.test_id,
        spec.kind,
        not result.fired,
        result.evaluable,
        0,
        spec.points,
        result.detail,
    )


def _evaluate_comprehensive_income_separator(
    table: TypedTable, spec: FormTestSpec
) -> FormTestOutcome:
    result = evaluate_form_test_comprehensive_income_separator(table, spec)
    return FormTestOutcome(
        spec.family,
        spec.test_id,
        spec.kind,
        not result.fired,
        result.evaluable,
        0,
        spec.points,
        result.detail,
    )


def _evaluate_equity_separator(
    table: TypedTable, spec: FormTestSpec
) -> FormTestOutcome:
    result = evaluate_form_test_equity_separator(table, spec)
    return FormTestOutcome(
        spec.family,
        spec.test_id,
        spec.kind,
        not result.fired,
        result.evaluable,
        0,
        spec.points,
        result.detail,
    )


def _evaluate_stock_comp_separator(
    table: TypedTable, spec: FormTestSpec
) -> FormTestOutcome:
    result = evaluate_form_test_stock_comp_separator(table, spec)
    return FormTestOutcome(
        spec.family,
        spec.test_id,
        spec.kind,
        not result.fired,
        result.evaluable,
        0,
        spec.points,
        result.detail,
    )


def _evaluate_deferred_tax_separator(
    table: TypedTable, spec: FormTestSpec
) -> FormTestOutcome:
    result = evaluate_form_test_deferred_tax_separator(table, spec)
    return FormTestOutcome(
        spec.family,
        spec.test_id,
        spec.kind,
        not result.fired,
        result.evaluable,
        0,
        spec.points,
        result.detail,
    )


def _evaluate_tax_reconciliation_separator(
    table: TypedTable, spec: FormTestSpec
) -> FormTestOutcome:
    result = evaluate_form_test_tax_reconciliation_separator(table, spec)
    return FormTestOutcome(
        spec.family,
        spec.test_id,
        spec.kind,
        not result.fired,
        result.evaluable,
        0,
        spec.points,
        result.detail,
    )


def _evaluate_lease_separator(table: TypedTable, spec: FormTestSpec) -> FormTestOutcome:
    result = evaluate_form_test_lease_separator(table, spec)
    return FormTestOutcome(
        spec.family,
        spec.test_id,
        spec.kind,
        not result.fired,
        result.evaluable,
        0,
        spec.points,
        result.detail,
    )


def _evaluate_form_separation(table: TypedTable, spec: FormTestSpec) -> FormTestOutcome:
    result = evaluate_form_test_form_separation(table, spec)
    return FormTestOutcome(
        spec.family,
        spec.test_id,
        spec.kind,
        not result.fired,
        result.evaluable,
        0,
        spec.points,
        result.detail,
    )
