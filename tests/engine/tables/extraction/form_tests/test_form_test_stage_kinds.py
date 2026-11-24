"""Form-test stage: every Step 3 kind registered, specimen outcomes.

The stage dispatches all five Step 3 kinds to a real evaluator;
each kind passes its priced specimen shape.
"""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.core.text.context import TableContext
from edgar_sec.engine.tables.extraction.form_tests.form_tests import evaluate_form_tests
from edgar_sec.engine.tables.extraction.form_specs.form_test_specs import (
    FORM_TEST_SPECS,
)
from edgar_sec.engine.tables.extraction.core.subjects.profile_constants import (
    TEST_DERIVATIVES_EVIDENCE,
    TEST_SEGMENT_FORM,
)
from edgar_sec.engine.tables.extraction.core.subjects.profiles import (
    PROFILES,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import (
    TypedTable,
    structure_table,
)

_STEP4_KINDS = (TEST_SEGMENT_FORM, TEST_DERIVATIVES_EVIDENCE)


def _table(rows: tuple[tuple[str, ...], ...], **context_kwargs: object) -> TypedTable:
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
    return structure_table(TableContext(geometry=geometry, **context_kwargs))


def _outcome(table: TypedTable, test_id: str):
    return next(o for o in evaluate_form_tests(table) if o.test_id == test_id)


def test_every_spec_kind_has_a_registered_evaluator() -> None:
    table = _table((("Caption", "1"),))
    for spec in FORM_TEST_SPECS:
        outcome = _outcome(table, spec.test_id)
        assert outcome.detail != "no evaluator for kind", spec.test_id


def test_specs_cover_every_declared_kind_but_step4s() -> None:
    declared = {kind for profile in PROFILES for kind in profile.form_tests} - set(
        _STEP4_KINDS
    )
    specified = {spec.kind for spec in FORM_TEST_SPECS}
    assert declared <= specified
    for spec in FORM_TEST_SPECS:
        profile = next(p for p in PROFILES if p.family == spec.family)
        assert spec.kind in profile.form_tests


def test_ladder_kind_passes_the_debt_column_ladder() -> None:
    table = _table(
        (
            ("", "2026", "2027", "2028", "2029", "2030", "Thereafter", "Total"),
            ("Long-term debt", "100", "200", "300", "400", "500", "600", "2,100"),
            ("Notes payable", "10", "20", "30", "40", "50", "60", "210"),
        )
    )
    assert _outcome(table, "debt_maturity_year_ladder").passed


def test_percentage_kind_passes_the_pure_percent_reconciliation() -> None:
    table = _table(
        (
            ("Federal statutory rate", "21.0 %", "21.0 %"),
            ("State income taxes, net of federal benefit", "2.3 %", "1.2 %"),
            ("Share-based payment awards", "(0.4 %)", "0.6 %"),
            ("Valuation allowance change", "1.5 %", "0.0 %"),
            ("Effective tax rate", "24.4 %", "22.8 %"),
        )
    )
    assert _outcome(table, "tax_rate_reconciliation_percentage_form").passed


def test_composition_kind_passes_pension_components() -> None:
    table = _table(
        (
            ("Service cost", "10"),
            ("Interest cost", "20"),
            ("Expected return on plan assets", "(15)"),
            ("Amortization of prior service cost", "3"),
            ("Net periodic benefit cost", "18"),
        )
    )
    assert _outcome(table, "pension_composition").passed


def test_seat_kind_passes_the_seated_balance_sheet() -> None:
    rows = (
        ("Total assets", "100"),
        ("Total liabilities", "60"),
        ("Total stockholders' equity", "40"),
    )
    seated = _table(rows, region="body")
    assert _outcome(seated, "balance_sheet_either_form").passed
    in_toc = _table(rows, region="body", in_toc_span=True)
    outcome = _outcome(in_toc, "balance_sheet_either_form")
    assert not outcome.passed and outcome.detail == "outside the statement seat"


def test_seat_kind_passes_the_equity_column_walk() -> None:
    table = _table(
        (
            ("", "Common stock", "Retained earnings", "Total"),
            ("Balance at beginning of period", "100", "50", "150"),
            ("Net income", "10", "(5)", "5"),
            ("Balance at end of period", "110", "45", "155"),
        ),
        region="body",
    )
    assert _outcome(table, "equity_column_walk").passed
