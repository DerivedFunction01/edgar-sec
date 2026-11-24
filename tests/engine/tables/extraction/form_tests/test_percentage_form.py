"""Percentage-form test: registry spec and specimen-shaped grids."""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.core.text.context import TableContext
from edgar_sec.engine.tables.extraction.form_tests.percentage_form import (
    evaluate_percentage_form,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_specs import (
    FORM_TEST_SPECS,
    form_test_specs_for,
)
from edgar_sec.engine.tables.extraction.form_specs.percentage_form_specs import (
    PERCENTAGE_SPECS,
    PERCENTAGE_SPECS_BY_FAMILY,
)
from edgar_sec.engine.tables.extraction.core.subjects.profile_constants import (
    TEST_PERCENTAGE_FORM,
)
from edgar_sec.engine.tables.extraction.core.subjects.profiles import (
    PROFILES_BY_FAMILY,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import (
    TypedTable,
    structure_table,
)

SPECS = form_test_specs_for("tax_reconciliation")
SPEC = next(spec for spec in SPECS if spec.kind == TEST_PERCENTAGE_FORM)


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


PURE_PERCENT = _table(
    (
        ("Federal statutory rate", "21.0 %", "21.0 %"),
        ("State income taxes, net of federal benefit", "2.3 %", "1.2 %"),
        ("Share-based payment awards", "(0.4 %)", "0.6 %"),
        ("Valuation allowance change", "1.5 %", "0.0 %"),
        ("Effective tax rate", "24.4 %", "22.8 %"),
    )
)
MIXED_AMOUNT_PERCENT = _table(
    (
        ("Income tax provision at statutory rate", "$ 1,213", "21.0 %"),
        ("State income taxes, net of federal benefit", "$ 302", "5.2 %"),
        ("Tax credits", "$ (58)", "(1.0 %)"),
        ("Effective income tax provision", "$ 1,457", "25.2 %"),
    )
)
PROVISION_DETAIL = _table(
    (
        ("Current federal", "$ 4,120", "$ 3,860"),
        ("Current state", "$ 910", "$ 845"),
        ("Current foreign", "$ 260", "$ 301"),
        ("Total current", "$ 5,290", "$ 5,006"),
        ("Deferred federal", "$ (1,140)", "$ (990)"),
        ("Deferred state", "$ (205)", "$ (176)"),
        ("Total provision for income taxes", "$ 3,945", "$ 3,840"),
    )
)
DEFERRED_COMPONENTS = _table(
    (
        ("Net operating loss carryforwards", "$ 15,978", "$ 13,514"),
        ("Tax credit carryforwards", "$ 2,410", "$ 2,102"),
        ("Total deferred tax assets", "$ 18,388", "$ 15,616"),
        ("Less: valuation allowance", "$ (18,388)", "$ (15,616)"),
        ("Net deferred tax assets", "$ —", "$ —"),
        ("Depreciation and amortization", "$ (6,230)", "$ (5,874)"),
        ("Net deferred tax liabilities", "$ (6,230)", "$ (5,874)"),
    )
)
INCIDENTAL_PERCENTS = _table(
    (
        ("Revenue growth", "12.4 %", "9.1 %"),
        ("Gross margin", "38.2 %", "36.7 %"),
        ("Operating margin", "11.0 %", "10.2 %"),
    )
)
ANCHOR_WITHOUT_CLOSURE = _table(
    (
        ("Federal statutory rate", "21.0 %", "21.0 %"),
        ("State income taxes, net of federal benefit", "2.3 %", "1.2 %"),
        ("Effective tax rate", "31.9 %", "30.5 %"),
    )
)
TWO_RATES_NO_ADJUSTMENT = _table(
    (
        ("Statutory federal income tax rate", "21.0 %", "21.0 %"),
        ("Effective income tax rate", "21.0 %", "21.0 %"),
    )
)


def test_percentage_spec_is_registry_data() -> None:
    profile = PROFILES_BY_FAMILY["tax_reconciliation"]
    assert TEST_PERCENTAGE_FORM in profile.form_tests
    assert [spec for spec in SPECS if spec.kind == TEST_PERCENTAGE_FORM] == [SPEC]
    assert SPEC in FORM_TEST_SPECS
    assert SPEC.kind == TEST_PERCENTAGE_FORM and SPEC.points == 3.0
    params = PERCENTAGE_SPECS_BY_FAMILY["tax_reconciliation"]
    assert params in PERCENTAGE_SPECS and params.family == SPEC.family
    assert params.closure_tolerance == 0.3 and params.min_adjustments == 1
    assert any("statutory" in token for token in params.anchor_tokens)
    assert any("effective" in token for token in params.total_tokens)
    assert profile.shape is not None
    for token in ("statutory", "adjustment", "effective", "percent", "close"):
        assert token in profile.shape


def test_deferred_tax_has_no_percentage_spec() -> None:
    deferred = PROFILES_BY_FAMILY["deferred_tax"]
    assert TEST_PERCENTAGE_FORM not in deferred.form_tests
    assert [
        s for s in form_test_specs_for("deferred_tax") if s.kind == TEST_PERCENTAGE_FORM
    ] == []
    support = deferred.support
    assert support is not None and support.quarterly_directed_recall == 0.942


def test_pure_percentage_reconciliation_passes() -> None:
    result = evaluate_percentage_form(PURE_PERCENT, SPEC)
    assert result.passed and result.evaluable and result.columns_closed == 2
    assert result.family == "tax_reconciliation" and result.points == 3.0


def test_mixed_amount_percent_reconciliation_passes() -> None:
    result = evaluate_percentage_form(MIXED_AMOUNT_PERCENT, SPEC)
    assert result.passed and result.columns_closed == 1


def test_provision_detail_fails_as_not_evaluable() -> None:
    result = evaluate_percentage_form(PROVISION_DETAIL, SPEC)
    assert not result.passed and not result.evaluable


def test_deferred_tax_components_fail_as_not_evaluable() -> None:
    result = evaluate_percentage_form(DEFERRED_COMPONENTS, SPEC)
    assert not result.passed and not result.evaluable


def test_incidental_percentages_fail_as_not_evaluable() -> None:
    result = evaluate_percentage_form(INCIDENTAL_PERCENTS, SPEC)
    assert not result.passed and not result.evaluable


def test_anchor_without_closure_fails_evaluable() -> None:
    result = evaluate_percentage_form(ANCHOR_WITHOUT_CLOSURE, SPEC)
    assert not result.passed and result.evaluable and result.columns_closed == 0


def test_two_rates_without_adjustments_fail() -> None:
    result = evaluate_percentage_form(TWO_RATES_NO_ADJUSTMENT, SPEC)
    assert not result.passed and result.evaluable
