"""Step 2 assignment-stage cure: the cascade can name the four.
The scored set covers every form-tested family, arbitration has
a priority seat for each, and member tables win their names."""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.cascade.classify import (
    candidate_scores,
    classify_table,
)
from edgar_sec.engine.tables.extraction.core.context import TableContext
from edgar_sec.engine.tables.extraction.form_specs.form_test_specs import (
    FORM_TEST_SPECS,
)
from edgar_sec.engine.tables.extraction.core.registry import FAMILY_PRIORITY
from edgar_sec.engine.tables.extraction.core.typed_rows import (
    TypedTable,
    structure_table,
)

FOUR = ("debt_maturity", "derivatives_hedging", "comprehensive_income", "ppe")


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


def test_scored_set_covers_every_form_tested_family() -> None:
    table = _table((("Caption", "1"),))
    scored = candidate_scores(table)
    for spec in FORM_TEST_SPECS:
        assert spec.family in scored, spec.family
    for family in FOUR:
        assert family in scored


def test_every_scored_family_has_a_priority_seat() -> None:
    table = _table((("Caption", "1"),))
    for family in candidate_scores(table):
        assert family in FAMILY_PRIORITY, family


def test_ppe_member_wins_its_name() -> None:
    table = _table(
        (
            ("Land", "100"),
            ("Building", "200"),
            ("Machinery and equipment", "300"),
            ("Furniture and fixtures", "50"),
            ("Leasehold improvements", "40"),
            ("Less: accumulated depreciation", "(150)"),
            ("Total property and equipment, net", "540"),
        )
    )
    assert classify_table(table).family == "ppe"


def test_comprehensive_income_member_wins_its_name() -> None:
    table = _table(
        (
            ("Net income", "100"),
            ("Other comprehensive income:", ""),
            ("Foreign currency translation adjustments", "5"),
            ("Unrealized gain on securities", "3"),
            ("Total other comprehensive income", "8"),
            ("Total comprehensive income", "108"),
        )
    )
    assert classify_table(table).family == "comprehensive_income"


def test_derivatives_member_wins_its_name() -> None:
    table = _table(
        (
            ("Interest rate swaps", "10"),
            ("Forward contracts", "20"),
            ("Derivatives designated as hedging instruments", "30"),
            ("Derivatives not designated as hedging instruments", "5"),
            ("Total derivative assets", "65"),
        )
    )
    assert classify_table(table).family == "derivatives_hedging"


def test_debt_maturity_row_ladder_wins_its_name() -> None:
    table = _table(
        (
            ("", "Amount"),
            ("2027", "100"),
            ("2028", "200"),
            ("2029", "300"),
            ("2030", "400"),
            ("2031", "500"),
            ("Thereafter", "600"),
            ("Total long-term debt", "2,100"),
            ("Less: current portion", "(100)"),
            ("Long-term debt, net of current portion", "2,000"),
        )
    )
    assert classify_table(table).family == "debt_maturity"
