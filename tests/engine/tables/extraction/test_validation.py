"""Identity evaluation over typed rows and its cascade integration."""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.classify import classify_table
from edgar_sec.engine.tables.extraction.context import TableContext
from edgar_sec.engine.tables.extraction.registry import IDENTITIES
from edgar_sec.engine.tables.extraction.typed_rows import (
    CaptionInfo,
    RowKind,
    TypedRow,
    TypedTable,
)
from edgar_sec.engine.tables.extraction.validation import evaluate_math


def _geometry() -> TableGeometry:
    return TableGeometry(
        table_index=0,
        render_result=TableRenderResult(
            ascii_text="",
            resolved_grid=ResolvedGrid(
                rows=(), column_alignments=(), column_widths=(), header_row_count=0
            ),
            confidence=1.0,
        ),
    )


def _table(rows: tuple[tuple[str, tuple[float | None, ...]], ...]) -> TypedTable:
    typed = tuple(
        TypedRow(label=label, values=values, kind=RowKind.DATA, raw=(label,))
        for label, values in rows
    )
    return TypedTable(
        context=TableContext(geometry=_geometry(), section=None, note=None),
        caption=CaptionInfo(
            lines=(),
            company=None,
            titles=(),
            audit_status=None,
            scale=None,
            continued=False,
            consumed_rows=0,
        ),
        periods=(),
        rows=typed,
        scale=None,
        header_rows=0,
        continued=False,
    )


def _outcome(table: TypedTable, family: str):
    return next(o for o in evaluate_math(table) if o.family == family)


def test_registry_prices_are_the_step3_figures() -> None:
    priced = {
        spec.family: (spec.name, spec.tier, spec.coverage, spec.closure)
        for spec in IDENTITIES
    }
    assert priced == {
        "balance_sheet": ("balance_sheet_either_form", "standard", 0.735, 0.977),
        "cash_flow": ("cash_flow_with_fx_leg", "standard", 0.430, 0.985),
        "income_statement": ("gross_profit_leg1", "weak", 0.247, 0.895),
    }
    assert all(spec.provenance == "step3:math_pricing" for spec in IDENTITIES)


def test_balance_sheet_two_row_form_closes() -> None:
    table = _table(
        (
            ("Total assets", (100.0,)),
            ("Total liabilities", (60.0,)),
            ("Total stockholders' equity", (40.0,)),
        )
    )
    outcome = _outcome(table, "balance_sheet")
    assert outcome.closed
    assert dict(outcome.keys) == {
        "total_assets": 100.0,
        "total_liabilities": 60.0,
        "total_equity": 40.0,
    }


def test_balance_sheet_combined_row_takes_precedence() -> None:
    table = _table(
        (
            ("Total assets", (100.0,)),
            ("Total liabilities", (60.0,)),
            ("Total stockholders' equity", (30.0,)),
            ("Total liabilities and stockholders' equity", (100.0,)),
        )
    )
    outcome = _outcome(table, "balance_sheet")
    assert outcome.closed
    assert dict(outcome.keys) == {"total_assets": 100.0, "combined": 100.0}


def test_balance_sheet_failure_is_an_outcome_not_an_absence() -> None:
    table = _table(
        (
            ("Total assets", (100.0,)),
            ("Total liabilities", (60.0,)),
            ("Total equity", (30.0,)),
        )
    )
    assert not _outcome(table, "balance_sheet").closed


def test_balance_sheet_needs_assets_and_one_liability_side_form() -> None:
    no_assets = _table((("Total liabilities", (60.0,)), ("Total equity", (40.0,))))
    assert all(o.family != "balance_sheet" for o in evaluate_math(no_assets))
    no_equity = _table((("Total assets", (100.0,)), ("Total liabilities", (60.0,))))
    assert all(o.family != "balance_sheet" for o in evaluate_math(no_equity))


def test_tolerance_half_percent_leg_and_two_unit_leg() -> None:
    within_pct = _table(
        (
            ("Total assets", (100000.0,)),
            ("Total liabilities", (60000.0,)),
            ("Total equity", (40400.0,)),
        )
    )
    assert _outcome(within_pct, "balance_sheet").closed
    beyond_pct = _table(
        (
            ("Total assets", (100000.0,)),
            ("Total liabilities", (60000.0,)),
            ("Total equity", (40600.0,)),
        )
    )
    assert not _outcome(beyond_pct, "balance_sheet").closed
    within_units = _table(
        (
            ("Total assets", (100.0,)),
            ("Total liabilities", (60.0,)),
            ("Total equity", (41.5,)),
        )
    )
    assert _outcome(within_units, "balance_sheet").closed


def test_first_valued_match_skips_valueless_key_rows() -> None:
    table = _table(
        (
            ("Total assets", (None,)),
            ("Total assets", (100.0,)),
            ("Total liabilities", (60.0,)),
            ("Total equity", (40.0,)),
        )
    )
    outcome = _outcome(table, "balance_sheet")
    assert outcome.closed
    assert dict(outcome.keys)["total_assets"] == 100.0


def test_only_the_first_value_column_is_read() -> None:
    table = _table(
        (
            ("Total assets", (100.0, 999.0)),
            ("Total liabilities", (60.0, 1.0)),
            ("Total equity", (40.0, 1.0)),
        )
    )
    assert _outcome(table, "balance_sheet").closed


def test_cash_flow_closes_without_the_fx_leg() -> None:
    table = _table(
        (
            ("Net cash provided by operating activities", (100.0,)),
            ("Net cash used in investing activities", (-30.0,)),
            ("Net cash provided by financing activities", (-20.0,)),
            ("Net increase in cash and cash equivalents", (50.0,)),
        )
    )
    outcome = _outcome(table, "cash_flow")
    assert outcome.closed
    assert "fx" not in dict(outcome.keys)


def test_cash_flow_closes_only_with_the_fx_leg() -> None:
    table = _table(
        (
            ("Net cash provided by operating activities", (100.0,)),
            ("Net cash used in investing activities", (-30.0,)),
            ("Net cash provided by financing activities", (-20.0,)),
            ("Effect of exchange rate changes on cash", (5.0,)),
            ("Net increase in cash and cash equivalents", (55.0,)),
        )
    )
    outcome = _outcome(table, "cash_flow")
    assert outcome.closed
    assert dict(outcome.keys)["fx"] == 5.0


def test_cash_flow_failure_and_signed_decrease() -> None:
    failing = _table(
        (
            ("Net cash provided by operating activities", (100.0,)),
            ("Net cash used in investing activities", (-30.0,)),
            ("Net cash provided by financing activities", (-20.0,)),
            ("Net increase in cash and cash equivalents", (60.0,)),
        )
    )
    assert not _outcome(failing, "cash_flow").closed
    decrease = _table(
        (
            ("Net cash used in operating activities", (-80.0,)),
            ("Net cash provided by investing activities", (10.0,)),
            ("Net cash provided by financing activities", (20.0,)),
            ("Net decrease in cash and cash equivalents", (-50.0,)),
        )
    )
    assert _outcome(decrease, "cash_flow").closed


def test_cash_flow_needs_all_four_key_rows() -> None:
    table = _table(
        (
            ("Net cash provided by operating activities", (100.0,)),
            ("Net cash used in investing activities", (-30.0,)),
            ("Net increase in cash and cash equivalents", (70.0,)),
        )
    )
    assert all(o.family != "cash_flow" for o in evaluate_math(table))


def test_income_leg1_closes_and_fails() -> None:
    closing = _table(
        (
            ("Total revenues", (200.0,)),
            ("Cost of goods sold", (120.0,)),
            ("Gross profit", (80.0,)),
        )
    )
    assert _outcome(closing, "income_statement").closed
    failing = _table(
        (
            ("Total revenues", (200.0,)),
            ("Cost of goods sold", (120.0,)),
            ("Gross profit", (70.0,)),
        )
    )
    assert not _outcome(failing, "income_statement").closed


def test_income_leg1_needs_a_gross_profit_row() -> None:
    table = _table(
        (
            ("Total revenues", (200.0,)),
            ("Cost of goods sold", (120.0,)),
            ("Operating income", (80.0,)),
        )
    )
    assert all(o.family != "income_statement" for o in evaluate_math(table))


def test_revenue_match_skips_excluded_labels() -> None:
    table = _table(
        (
            ("Sales tax payable", (999.0,)),
            ("Total sales", (200.0,)),
            ("Cost of sales", (120.0,)),
            ("Gross profit", (80.0,)),
        )
    )
    outcome = _outcome(table, "income_statement")
    assert outcome.closed
    assert dict(outcome.keys)["revenue"] == 200.0


def test_math_confirmation_crosses_the_assignment_floor() -> None:
    table = _table(
        (
            ("Total liabilities", (60.0,)),
            ("Total assets", (100.0,)),
            ("Total stockholders' equity", (40.0,)),
        )
    )
    without = classify_table(table, math_outcomes=())
    assert without.family == "other"
    result = classify_table(table)
    assert result.family == "balance_sheet"
    assert result.tier == "evidence"
    math_entries = [e for e in result.evidence if e.group == "math"]
    assert [(e.detail, e.points) for e in math_entries] == [
        ("balance_sheet_either_form closed", 2.39)
    ]
    assert abs(result.score - (without.score + 2.39)) < 1e-9


def test_failed_identity_signals_at_zero_points() -> None:
    table = _table(
        (
            ("Cash and cash equivalents", (10.0,)),
            ("Total current assets", (60.0,)),
            ("Total assets", (100.0,)),
            ("Total liabilities", (60.0,)),
            ("Total stockholders' equity", (30.0,)),
        )
    )
    without = classify_table(table, math_outcomes=())
    result = classify_table(table)
    assert result.family == without.family == "balance_sheet"
    assert abs(result.score - without.score) < 1e-9
    math_entries = [e for e in result.evidence if e.group == "math"]
    assert [(e.detail, e.points) for e in math_entries] == [
        ("balance_sheet_either_form failed", 0.0)
    ]


def test_income_confirmation_pays_the_repriced_points() -> None:
    table = _table(
        (
            ("Total revenues", (200.0,)),
            ("Cost of goods sold", (120.0,)),
            ("Gross profit", (80.0,)),
            ("Operating expenses", (50.0,)),
            ("Total operating expenses", (50.0,)),
            ("Net income", (30.0,)),
        )
    )
    result = classify_table(table)
    assert result.family == "income_statement"
    math_entries = [e for e in result.evidence if e.group == "math"]
    assert [(e.detail, e.points) for e in math_entries] == [
        ("gross_profit_leg1 closed", 2.11)
    ]
