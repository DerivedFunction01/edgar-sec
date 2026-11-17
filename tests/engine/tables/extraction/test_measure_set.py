"""Measure-set kind: the Step 3 forms pass, their priced falses fail."""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.context import TableContext
from edgar_sec.engine.tables.extraction.form_tests import evaluate_form_tests
from edgar_sec.engine.tables.extraction.typed_rows import TypedTable, structure_table


def _table(rows: tuple[tuple[str, ...], ...]) -> TypedTable:
    geometry = TableGeometry(
        table_index=0,
        render_result=TableRenderResult(
            ascii_text="",
            resolved_grid=ResolvedGrid(
                rows=rows,
                column_alignments=(),
                column_widths=(),
                header_row_count=0,
            ),
            confidence=1.0,
        ),
    )
    return structure_table(TableContext(geometry=geometry))


def _outcome(table: TypedTable, test_id: str):
    return next(o for o in evaluate_form_tests(table) if o.test_id == test_id)


def test_item_703_form_passes_on_its_filed_measures() -> None:
    table = _table(
        (
            (
                "Period",
                "Total Number of Shares Purchased",
                "Average Price Paid Per Share",
                "Total Number of Shares Purchased as Part of Publicly "
                "Announced Plans or Programs",
                "Maximum Number of Shares that May Yet Be Purchased "
                "Under the Plans or Programs",
            ),
            ("October 1 - 31", "10,000", "$ 5.00", "10,000", "1,000,000"),
        )
    )
    assert _outcome(table, "shares_purchased_measure_set").passed


def test_repurchase_lines_inside_hosts_do_not_pass() -> None:
    equity = _table(
        (
            ("Repurchase of common stock", "(1,000)"),
            ("Balance at December 31", "50,000"),
        )
    )
    assert not _outcome(equity, "shares_purchased_measure_set").passed
    cash_flow = _table((("Repurchases of common stock", "(5,000)"),))
    assert not _outcome(cash_flow, "shares_purchased_measure_set").passed


def test_valuation_assumptions_pass_on_the_input_set() -> None:
    table = _table(
        (
            ("", "2025", "2024"),
            ("Expected volatility", "45 %", "47 %"),
            ("Expected dividend yield", "0 %", "0 %"),
            ("Expected term (in years)", "6.0", "6.1"),
            ("Risk-free interest rate", "4.1 %", "3.9 %"),
        )
    )
    outcome = _outcome(table, "valuation_model_assumptions_measure_set")
    assert outcome.passed


def test_level_3_unobservable_inputs_are_refused() -> None:
    table = _table(
        (
            ("Significant unobservable inputs (Level 3)", ""),
            ("Discount rate", "9 %"),
            ("Volatility", "30 %"),
            ("Interest rate", "5 %"),
        )
    )
    outcome = _outcome(table, "valuation_model_assumptions_measure_set")
    assert not outcome.passed
    assert "refused term present" in outcome.detail


def test_warrant_activity_passes_on_the_warrant_subject() -> None:
    table = _table(
        (
            ("", "Number of Warrants", "Weighted Average Exercise Price"),
            ("Warrants outstanding at beginning of period", "1,000", "$ 2.00"),
            ("Granted", "500", "$ 3.00"),
            ("Exercised", "(100)", "$ 2.50"),
            ("Expired", "(50)", "$ 4.00"),
            ("Warrants outstanding at end of period", "1,350", "$ 2.75"),
        )
    )
    assert _outcome(table, "warrant_activity_rollforward").passed


def test_stock_comp_activity_does_not_pass_the_warrant_test() -> None:
    table = _table(
        (
            ("", "Number of Options", "Weighted Average Exercise Price"),
            ("Options outstanding at beginning of period", "1,000", "$ 2.00"),
            ("Granted", "500", "$ 3.00"),
            ("Exercised", "(100)", "$ 2.50"),
            ("Forfeited", "(50)", "$ 4.00"),
            ("Options outstanding at end of period", "1,350", "$ 2.75"),
        )
    )
    outcome = _outcome(table, "warrant_activity_rollforward")
    assert not outcome.passed
    assert "subject absent" in outcome.detail


def test_warrant_listing_passes_and_plan_tables_do_not() -> None:
    listing = _table(
        (
            (
                "Class of Warrant",
                "Number Outstanding",
                "Exercise Price",
                "Remaining Contractual Life",
            ),
            ("Series A Warrants", "100", "$ 1.00", "3.5 years"),
        )
    )
    assert _outcome(listing, "warrant_outstanding_listing").passed
    plan = _table(
        (
            ("Plan Category", "Number of Securities", "Weighted Average Price"),
            (
                "Equity compensation plans approved by security holders",
                "1,000",
                "$ 5.00",
            ),
        )
    )
    assert not _outcome(plan, "warrant_outstanding_listing").passed


def test_combined_statement_passes_all_three_classes() -> None:
    table = _table(
        (
            ("Total revenues", "1,000"),
            ("Gross profit", "600"),
            ("Income from operations", "200"),
            ("Net income", "150"),
            ("Foreign currency translation adjustments", "10"),
            ("Unrealized gain on investments", "5"),
            ("Comprehensive income", "165"),
        )
    )
    assert _outcome(table, "combined_operations_ci_measure_set").passed


def test_standalone_comprehensive_income_is_not_the_combined_form() -> None:
    table = _table(
        (
            ("Net income", "150"),
            ("Other comprehensive income", "15"),
            ("Comprehensive income", "165"),
        )
    )
    assert not _outcome(table, "combined_operations_ci_measure_set").passed


def test_income_statement_alone_is_not_the_combined_form() -> None:
    table = _table(
        (
            ("Total revenues", "1,000"),
            ("Gross profit", "600"),
            ("Net income", "150"),
        )
    )
    assert not _outcome(table, "combined_operations_ci_measure_set").passed
