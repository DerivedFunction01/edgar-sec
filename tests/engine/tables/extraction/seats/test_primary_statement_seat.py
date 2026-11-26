"""Primary-statement seat tests: registry data and specimen forms.

Specimens are shaped from the Step 6 verdict's false classes:
summaries, recasts, compositions and sibling statements.
"""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.core.text.context import TableContext
from edgar_sec.engine.tables.extraction.seats.specs.seat_test_specs import (
    SEAT_TEST_SPECS_BY_FAMILY,
    SeatTestSpec,
)
from edgar_sec.engine.tables.extraction.core.subjects.profile_constants import (
    TEST_PRIMARY_STATEMENT_SEAT,
)
from edgar_sec.engine.tables.extraction.core.subjects.profiles import (
    PROFILES_BY_FAMILY,
)
from edgar_sec.engine.tables.extraction.core.registry import (
    CORE_FAMILIES,
    IDENTITIES_BY_FAMILY,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import (
    CaptionInfo,
    RowKind,
    TypedRow,
    TypedTable,
)
from edgar_sec.engine.tables.extraction.core.validation import evaluate_math

SEAT_FAMILIES = {"income_statement", "balance_sheet", "cash_flow", "equity_statement"}


def _spec(family: str) -> SeatTestSpec:
    spec = SEAT_TEST_SPECS_BY_FAMILY[family]
    assert spec is not None
    return spec


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
    return next((o for o in evaluate_math(table) if o.family == family), None)


def _seated(spec: SeatTestSpec, context: TableContext) -> bool:
    return (
        context.region == spec.seat_region
        and context.in_toc_span == spec.in_toc_span
        and context.in_closing_span == spec.in_closing_span
    )


def test_seat_tests_declared_for_exactly_the_core_statement_families() -> None:
    assert set(CORE_FAMILIES) == SEAT_FAMILIES
    declared = set(SEAT_TEST_SPECS_BY_FAMILY)
    assert declared == SEAT_FAMILIES
    for family in SEAT_FAMILIES:
        profile = PROFILES_BY_FAMILY[family]
        assert TEST_PRIMARY_STATEMENT_SEAT in profile.form_tests


def test_seat_facts_are_the_statement_seat() -> None:
    for family in SEAT_FAMILIES:
        spec = _spec(family)
        assert spec.seat_region == "body"
        assert spec.in_toc_span is False
        assert spec.in_closing_span is False
        assert (spec.tolerance_abs, spec.tolerance_rel) == (2.0, 0.005)


def test_seat_facts_refuse_toc_closing_and_genre_regions() -> None:
    spec = _spec("balance_sheet")
    body = TableContext(geometry=_geometry(), region="body")
    assert _seated(spec, body)
    for refused in (
        TableContext(geometry=_geometry(), region="body", in_toc_span=True),
        TableContext(geometry=_geometry(), region="body", in_closing_span=True),
        TableContext(geometry=_geometry(), region="cover"),
        TableContext(geometry=_geometry(), region="signature"),
        TableContext(geometry=_geometry(), region="exhibit"),
    ):
        assert not _seated(spec, refused)


def test_identities_align_with_the_priced_registry_where_priced() -> None:
    assert _spec("balance_sheet").identity == IDENTITIES_BY_FAMILY["balance_sheet"].name
    assert _spec("cash_flow").identity == IDENTITIES_BY_FAMILY["cash_flow"].name
    income = _spec("income_statement")
    assert IDENTITIES_BY_FAMILY["income_statement"].name == "gross_profit_leg1"
    assert income.identity == "revenue_to_net_income_descent"
    assert "gross_profit" in income.required_roles
    assert "equity_statement" not in IDENTITIES_BY_FAMILY
    assert _spec("equity_statement").identity == "equity_column_walk"


def test_required_roles_are_each_statements_own_totals() -> None:
    balance = _spec("balance_sheet")
    assert balance.required_roles == ("total_assets",)
    assert balance.either_roles == (
        ("total_liabilities", "total_equity"),
        ("combined",),
    )
    cash = _spec("cash_flow")
    assert cash.required_roles == ("operating", "investing", "financing", "change")
    assert cash.ordered_roles == cash.required_roles
    assert "fx" in cash.optional_roles
    income = _spec("income_statement")
    assert income.required_roles == ("revenue", "cogs", "gross_profit", "net_income")
    assert income.ordered_roles[-1] == "net_income"
    assert income.ordered_roles[0] == "revenue"
    equity = _spec("equity_statement")
    assert equity.required_roles == (
        "beginning_balance",
        "movement",
        "ending_balance",
        "component_columns",
        "total_column",
    )
    assert equity.ordered_roles == ("beginning_balance", "ending_balance")


def test_balance_sheet_identity_closes_only_on_the_statement_form() -> None:
    statement = _table(
        (
            ("Total assets", (100.0,)),
            ("Total liabilities", (60.0,)),
            ("Total stockholders' equity", (40.0,)),
        )
    )
    outcome = _outcome(statement, "balance_sheet")
    assert outcome is not None and outcome.closed
    composition = _table(
        (
            ("Level 3 assets", (100.0,)),
            ("Total fair value", (100.0,)),
        )
    )
    assert _outcome(composition, "balance_sheet") is None


def test_cash_flow_sections_sum_only_on_the_statement_form() -> None:
    statement = _table(
        (
            ("Net cash provided by operating activities", (50.0,)),
            ("Net cash used in investing activities", (-20.0,)),
            ("Net cash used in financing activities", (-10.0,)),
            ("Net increase in cash and cash equivalents", (20.0,)),
        )
    )
    outcome = _outcome(statement, "cash_flow")
    assert outcome is not None and outcome.closed
    summary = _table(
        (
            ("Net income", (20.0,)),
            ("Depreciation and amortization", (5.0,)),
            ("Changes in operating assets and liabilities", (-5.0,)),
        )
    )
    assert _outcome(summary, "cash_flow") is None


def test_income_descent_first_leg_fails_on_summary_forms() -> None:
    statement = _table(
        (
            ("Total revenues", (100.0,)),
            ("Cost of revenues", (60.0,)),
            ("Gross profit", (40.0,)),
            ("Net income", (15.0,)),
        )
    )
    outcome = _outcome(statement, "income_statement")
    assert outcome is not None and outcome.closed
    summary = _table(
        (
            ("Total revenues", (100.0,)),
            ("Net income", (15.0,)),
        )
    )
    assert _outcome(summary, "income_statement") is None


def test_equity_walk_closes_block_stacked_segments() -> None:
    from edgar_sec.engine.tables.extraction.seats.statement_seat import (
        _column_walk,
    )

    spec = _spec("equity_statement")
    stacked = _table(
        (
            ("Balance at beginning of period", (100.0,)),
            ("Net income", (10.0,)),
            ("Balance at end of period", (110.0,)),
            ("Balance at beginning of period", (200.0,)),
            ("Dividends declared", (-20.0,)),
            ("Balance at end of period", (180.0,)),
        )
    )
    assert _column_walk(stacked, spec) >= 1
    single = _table(
        (
            ("Balance at beginning of period", (100.0,)),
            ("Net income", (10.0,)),
            ("Balance at end of period", (110.0,)),
        )
    )
    assert _column_walk(single, spec) >= 1


def test_equity_walk_closes_per_column_and_in_total() -> None:
    spec = _spec("equity_statement")
    columns = {"common_stock": (100.0, 10.0, 110.0), "retained": (50.0, -5.0, 45.0)}
    for beginning, movement, ending in columns.values():
        assert beginning + movement == ending
    assert sum(column[2] for column in columns.values()) == 155.0
    summary_roles = {"ending_balance", "total_column"}
    assert not set(spec.required_roles) <= summary_roles
