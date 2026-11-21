"""Form-test stage: walk specs as data, arithmetic closure as evidence."""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.cascade.classify import candidate_scores
from edgar_sec.engine.tables.extraction.cascade.geometry_scoring import score_geometry
from edgar_sec.engine.tables.extraction.cascade.geometry_text import (
    geometry_text_from_table,
)
from edgar_sec.engine.tables.extraction.core.context import TableContext
from edgar_sec.engine.tables.extraction.form_tests.form_tests import evaluate_form_tests
from edgar_sec.engine.tables.extraction.form_specs.form_test_specs import (
    FORM_TEST_SPECS,
    form_test_specs_for,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_types import (
    FormTestOutcome,
    FormTestSpec,
)
from edgar_sec.engine.tables.extraction.form_specs.walk_specs import (
    WALK_SPECS_BY_TEST_ID,
)
from edgar_sec.engine.tables.extraction.core.profiles import (
    FORM_TESTS,
    TEST_SEGMENT_FORM,
    TEST_WALK,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import (
    CaptionInfo,
    ColumnPeriod,
    RowKind,
    TypedRow,
    TypedTable,
)

_WALK_FAMILIES = {
    "aoci_rollforward",
    "comprehensive_income",
    "stock_comp_rollforward",
    "eps_reconciliation",
}


def _kind(label: str, values: tuple) -> RowKind:
    if not any(value is not None for value in values):
        return RowKind.SECTION
    if label.lower().startswith("total"):
        return RowKind.TOTAL
    if "subtotal" in label.lower():
        return RowKind.SUBTOTAL
    return RowKind.DATA


def _table(rows: list[tuple[str, tuple]]) -> TypedTable:
    width = max((len(values) for _, values in rows), default=0)
    geometry = TableGeometry(
        table_index=0,
        render_result=TableRenderResult(
            ascii_text="",
            resolved_grid=ResolvedGrid(
                rows=(), column_alignments=(), column_widths=(), header_row_count=0
            ),
            confidence=1.0,
        ),
    )
    typed = tuple(
        TypedRow(
            label=label,
            values=tuple(values) + (None,) * (width - len(values)),
            kind=_kind(label, tuple(values)),
            raw=(label,),
        )
        for label, values in rows
    )
    return TypedTable(
        context=TableContext(geometry=geometry),
        caption=CaptionInfo((), None, (), None, None, False, 0),
        periods=tuple(
            ColumnPeriod(index + 1, None, None, None) for index in range(width)
        ),
        rows=typed,
        scale=None,
        header_rows=0,
        continued=False,
    )


def _outcome(table: TypedTable, family: str) -> FormTestOutcome:
    return next(o for o in evaluate_form_tests(table) if o.family == family)


_AOCI_WALK = [
    ("Balance at beginning of period", (100.0, 40.0)),
    ("Unrealized gains arising during the period", (10.0, 5.0)),
    ("Amounts reclassified from accumulated other comprehensive income", (-2.0, None)),
    ("Net current-period other comprehensive income", (8.0, 5.0)),
    ("Balance at end of period", (108.0, 45.0)),
]

_CI_WALK = [
    ("Net income", (500.0,)),
    ("Unrealized gain on securities", (20.0,)),
    ("Foreign currency translation adjustment", (-5.0,)),
    ("Other comprehensive income, net of tax", (15.0,)),
    ("Comprehensive income", (515.0,)),
]

_STOCK_WALK = [
    ("Outstanding at beginning of year", (1000.0, 10.0)),
    ("Granted", (200.0, 12.0)),
    ("Exercised", (-100.0, 9.0)),
    ("Forfeited", (-50.0, 11.0)),
    ("Outstanding at end of year", (1050.0, 10.5)),
    ("Options exercisable at end of year", (700.0, 9.5)),
]

_EPS_WALK = [
    ("Basic EPS", ()),
    ("Income available to common stockholders", (1000.0, 500.0, 2.0)),
    ("Effect of dilutive securities:", ()),
    ("Stock options", (None, 50.0, None)),
    ("Convertible notes", (60.0, 30.0, None)),
    ("Diluted EPS", ()),
    ("Income available to common stockholders", (1060.0, 580.0, 1.83)),
]


def test_walk_specs_are_registry_data_for_the_four_families() -> None:
    walk_specs = [spec for spec in FORM_TEST_SPECS if spec.kind == TEST_WALK]
    assert {spec.family for spec in walk_specs} == _WALK_FAMILIES
    for spec in walk_specs:
        assert spec.kind in FORM_TESTS
        assert spec.beginning and spec.ending and spec.points > 0.0
    eps_id = form_test_specs_for("eps_reconciliation")[0].test_id
    assert WALK_SPECS_BY_TEST_ID[eps_id].min_columns == 2
    assert {spec.test_id for spec in walk_specs} == set(WALK_SPECS_BY_TEST_ID)
    assert [s for s in form_test_specs_for("pension") if s.kind == TEST_WALK] == []


def test_aoci_walk_passes_with_an_arithmetic_subtotal_row() -> None:
    outcome = _outcome(_table(_AOCI_WALK), "aoci_rollforward")
    assert outcome.passed and outcome.evaluable and outcome.columns_closed == 2


def test_aoci_walk_stays_open_when_the_ending_does_not_reconcile() -> None:
    rows = [*_AOCI_WALK[:-1], ("Balance at end of period", (999.0, 999.0))]
    outcome = _outcome(_table(rows), "aoci_rollforward")
    assert outcome.evaluable and not outcome.passed


def test_aoci_composition_twin_has_no_walk_to_evaluate() -> None:
    table = _table(
        [
            ("Foreign currency translation adjustments", (30.0,)),
            ("Unrealized gains on securities", (50.0,)),
            ("Pension adjustments", (20.0,)),
            ("Total accumulated other comprehensive income", (100.0,)),
        ]
    )
    outcome = _outcome(table, "aoci_rollforward")
    assert not outcome.evaluable and not outcome.passed


def test_comprehensive_income_boundary_walk_passes() -> None:
    outcome = _outcome(_table(_CI_WALK), "comprehensive_income")
    assert outcome.passed and outcome.columns_closed == 1


def test_comprehensive_income_walk_does_not_fire_on_the_aoci_twin() -> None:
    table = _table(_AOCI_WALK)
    assert _outcome(table, "aoci_rollforward").passed
    ci = _outcome(table, "comprehensive_income")
    assert not ci.evaluable and not ci.passed


def test_stock_comp_activity_walk_passes_on_the_share_column() -> None:
    outcome = _outcome(_table(_STOCK_WALK), "stock_comp_rollforward")
    assert outcome.passed and outcome.columns_closed == 1


def test_stock_comp_snapshot_and_adjacent_balances_do_not_pass() -> None:
    snapshot = _table(
        [
            ("Options outstanding", (1000.0,)),
            ("Options exercisable", (600.0,)),
            ("Shares available for future issuance", (300.0,)),
        ]
    )
    assert not _outcome(snapshot, "stock_comp_rollforward").evaluable
    adjacent = _table(
        [
            ("Outstanding at beginning of year", (1000.0,)),
            ("Outstanding at end of year", (1000.0,)),
        ]
    )
    outcome = _outcome(adjacent, "stock_comp_rollforward")
    assert outcome.evaluable and not outcome.passed


def test_eps_walk_passes_on_numerator_and_denominator_columns() -> None:
    outcome = _outcome(_table(_EPS_WALK), "eps_reconciliation")
    assert outcome.passed and outcome.columns_closed == 2


def test_eps_walk_rejects_statement_face_lines() -> None:
    table = _table(
        [
            ("Revenues", (900.0,)),
            ("Net income", (100.0,)),
            ("Basic earnings per share", (2.0,)),
            ("Diluted earnings per share", (1.83,)),
        ]
    )
    outcome = _outcome(table, "eps_reconciliation")
    assert not outcome.passed


def test_eps_walk_rejects_antidilutive_and_per_share_tables() -> None:
    antidilutive = _table(
        [
            ("Common stock options", (300.0,)),
            ("Restricted stock units", (120.0,)),
            ("Convertible notes", (80.0,)),
        ]
    )
    assert not _outcome(antidilutive, "eps_reconciliation").evaluable
    per_share = _table(
        [
            ("Basic earnings per share", (2.0, 1.9)),
            ("Diluted earnings per share", (1.83, 1.75)),
        ]
    )
    assert not _outcome(per_share, "eps_reconciliation").passed


def test_walk_tolerance_is_the_pricing_tolerance() -> None:
    rows = [*_AOCI_WALK[:-1], ("Balance at end of period", (109.0, 45.0))]
    assert _outcome(_table(rows), "aoci_rollforward").passed
    rows = [*_AOCI_WALK[:-1], ("Balance at end of period", (130.0, 90.0))]
    assert not _outcome(_table(rows), "aoci_rollforward").passed


def test_a_kind_without_an_evaluator_never_scores() -> None:
    spec = FormTestSpec(
        "segment_reporting", TEST_SEGMENT_FORM, "segment_form_probe", 3.0
    )
    outcomes = evaluate_form_tests(_table(_AOCI_WALK), specs=(spec,))
    assert outcomes[0].passed is False and outcomes[0].evaluable is False


def test_stage_feeds_the_signature_competition() -> None:
    geometry = geometry_text_from_table(_table(_AOCI_WALK))
    scores = score_geometry(geometry)
    assert scores["aoci_rollforward"].by_channel["form_test"] == 3.0
    assert any(
        entry.channel == "form_test" and entry.points == 3.0
        for entry in scores["aoci_rollforward"].evidence
    )


def test_stage_feeds_the_cascade_for_seated_families() -> None:
    score, evidence = candidate_scores(_table(_AOCI_WALK))["aoci_rollforward"]
    assert any(entry.group == "form_test" and entry.points == 3.0 for entry in evidence)
    assert score >= 3.0
    twin = _table(
        [
            ("Foreign currency translation adjustments", (30.0,)),
            ("Total accumulated other comprehensive income", (30.0,)),
        ]
    )
    _, twin_evidence = candidate_scores(twin)["aoci_rollforward"]
    assert not any(entry.group == "form_test" for entry in twin_evidence)
