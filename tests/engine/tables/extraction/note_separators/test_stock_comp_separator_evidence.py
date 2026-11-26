"""Stock comp separator (TEST_STOCK_COMP_SEPARATOR): legs, gate, assignment."""

from __future__ import annotations

import edgar_sec.engine.tables.extraction.note_separators.stock_comp_separator_evidence as _sse
from edgar_sec.engine.tables.ascii_html.model.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.cascade.competition import compete
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
)
from edgar_sec.engine.tables.extraction.core.text.context import TableContext
from edgar_sec.engine.tables.extraction.evidence.form.core_form_evidence import (
    failing_core_form_outcome as _CORE_FORM_OUTCOME,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_specs import (
    FORM_TEST_SPECS,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_types import (
    FormTestOutcome,
)
from edgar_sec.engine.tables.extraction.form_tests.form_tests import evaluate_form_tests
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
    CompetitionResult,
    FamilyScore,
)
from edgar_sec.engine.tables.extraction.core.subjects.profile_constants import (
    PROV_STOCK_COMP_SEPARATOR,
    TEST_STOCK_COMP_SEPARATOR,
)
from edgar_sec.engine.tables.extraction.core.subjects.profiles import (
    profile_for,
)
from edgar_sec.engine.tables.extraction.note_separators.stock_comp_separator_evidence import (
    StockCompSeparatorText,
    apply_stock_comp_assignment,
    evaluate_form_test_stock_comp_separator,
    evaluate_stock_comp_separator,
)
from edgar_sec.engine.tables.extraction.note_separators.stock_comp_separator_specs import (
    STOCK_COMP_SEPARATOR_SPECS,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import structure_table
from edgar_sec.foundation.text.date_patterns import (
    YEAR_TOKEN_SEARCH_RE as _HOME_YEAR_RE,
)

SPEC = STOCK_COMP_SEPARATOR_SPECS["stock_comp_rollforward"]
FAMILY = "stock_comp_rollforward"
ANCHOR = "valuation_model_assumptions"


def _eval(table_text: str):
    return evaluate_stock_comp_separator(StockCompSeparatorText(table_text), SPEC)


def _listing(*years: str) -> str:
    header = "Grant | " + " | ".join(years)
    body = [f"Options granted in {y} | 100 | 200" for y in years]
    return "\n".join([header, *body])


def _spec():
    return next(s for s in FORM_TEST_SPECS if s.test_id == "stock_comp_separator")


def test_kind_is_declared_as_form_test_data():
    entry = next(
        s
        for s in FORM_TEST_SPECS
        if s.family == FAMILY and s.kind == TEST_STOCK_COMP_SEPARATOR
    )
    assert entry.test_id == "stock_comp_separator"
    assert entry.points == 0.0
    assert entry.provenance == PROV_STOCK_COMP_SEPARATOR
    assert SPEC.family == FAMILY
    assert TEST_STOCK_COMP_SEPARATOR in profile_for(FAMILY).form_tests


def test_spec_carries_the_priced_composition():
    legs = [(leg.leg_id, leg.kind, leg.scope) for leg in SPEC.legs]
    assert legs == [
        ("span_ge_5", "span", "claim-local"),
        ("seat_bound", "seat_bound", "claim-local"),
        ("warrant_vocab", "warrant", "claim-local"),
        ("available_pool", "available", "claim-local"),
        ("assign_other", "assign_other", "set-level"),
    ]
    anchor = next(leg for leg in SPEC.legs if leg.kind == "assign_other")
    assert anchor.anchor_family == ANCHOR
    span = next(leg for leg in SPEC.legs if leg.kind == "span")
    assert span.limit == 5
    seat_bound = next(leg for leg in SPEC.legs if leg.kind == "seat_bound")
    assert seat_bound.limit == 3


def test_packet_and_rows_surfaces_agree():
    rows = (
        ("Options granted", "2011", "2012", "2013", "2016", "2017", "2018"),
        ("Exercised", "10", "20", "30", "40", "50", "60"),
    )
    via_rows = evaluate_stock_comp_separator(
        StockCompSeparatorText.from_rows(rows), SPEC
    )
    via_packet = evaluate_stock_comp_separator(
        StockCompSeparatorText.from_packet(
            {
                "table_text": "Options granted | 2011 | 2012 | 2013 | 2016 | 2017"
                " | 2018\nExercised | 10 | 20 | 30 | 40 | 50 | 60"
            }
        ),
        SPEC,
    )
    assert via_rows == via_packet
    assert via_rows.fired


def test_recognizer_homes():
    assert _sse.YEAR_TOKEN_SEARCH_RE is _HOME_YEAR_RE
    assert _sse.fired_separator_outcome is _CORE_FORM_OUTCOME


# ---------------- the claim-local leg ----------------


def test_leg_span_ge_5_fires_on_six_years():
    verdict = _eval(_listing("2011", "2012", "2013", "2016", "2017", "2018"))
    assert verdict.fired
    assert verdict.legs == ("span_ge_5",)


def test_leg_span_ge_5_fires_at_the_boundary():
    verdict = _eval(_listing("2019", "2020", "2021", "2022", "2023"))
    assert verdict.fired
    assert verdict.legs == ("span_ge_5",)


def test_leg_span_clear_below_five():
    verdict = _eval(_listing("2022", "2023", "2024", "2025"))
    assert not verdict.fired
    assert verdict.legs == ()


def test_leg_span_counts_distinct_years_only():
    text = "Grant | 2023 | 2023\nGranted in 2023 | 1 | 2\nGranted in 2024 | 3 | 4"
    verdict = _eval(text)
    assert not verdict.fired


def test_empty_grid_is_unevaluable():
    verdict = _eval("")
    assert not verdict.fired
    assert not verdict.evaluable


# ---------------- the C2 claim-local legs ----------------


def test_seat_bound_fires_when_the_seat_reader_does_not_admit():
    # Activity stubs without a granted row: the derived seat
    # form does not admit, and no bookend exception holds.
    table = _table(
        [
            ("Shares issued under the plan", "100", "200"),
            ("Shares repurchased", "10", "20"),
        ]
    )
    verdict = evaluate_form_test_stock_comp_separator(table, _spec())
    assert verdict.fired and verdict.legs == ("seat_bound",)


def test_seat_bound_holds_under_the_bookend_exception():
    # Balance bookends with three activity rows: Xb protects
    # the claim even though the seat reader does not admit it.
    table = _table(
        [
            ("Balance at December 31, 2023", "100"),
            ("Issued", "10"),
            ("Exercised", "(5)"),
            ("Forfeited", "(2)"),
            ("Balance at December 31, 2024", "103"),
        ]
    )
    verdict = evaluate_form_test_stock_comp_separator(table, _spec())
    assert not verdict.fired and verdict.legs == ()


def test_seat_bound_holds_under_the_waep_exception_without_bookends():
    # Price-form grid: exercise-price range buckets under a
    # weighted-average-exercise-price column, no bookend rows.
    # The WAEP column excepts the claim from seat_bound on its
    # own — the price-form variant carries no bookends for Xb.
    table = _table(
        [
            (
                "Exercise price range",
                "Shares subject to outstanding options",
                "Weighted average exercise price",
            ),
            ("$0.01 - $5.00", "100", "$2.50"),
            ("$5.01 - $10.00", "200", "$7.50"),
            ("$10.01 and above", "50", "$12.00"),
        ]
    )
    surfaces = StockCompSeparatorText.from_table(table).surfaces
    assert surfaces is not None
    assert surfaces.col_waep and not surfaces.bookend
    assert not surfaces.seat_admitted
    verdict = evaluate_form_test_stock_comp_separator(table, _spec())
    assert not verdict.fired and verdict.legs == ()


def test_waep_exception_does_not_mute_the_warrant_leg():
    # The WAEP exception touches seat_bound only: warrant
    # vocabulary under a WAEP column still fires warrant_vocab,
    # and seat_bound adds nothing beside it.
    table = _table(
        [
            ("", "Warrants", "Weighted average exercise price"),
            ("Warrants granted", "100", "5.00"),
            ("Warrants exercised", "10", "5.00"),
            ("Warrants forfeited", "2", "5.00"),
        ]
    )
    verdict = evaluate_form_test_stock_comp_separator(table, _spec())
    assert verdict.fired and verdict.legs == ("warrant_vocab",)


def test_warrant_vocab_fires_on_an_admitted_geometry():
    table = _table(
        [
            ("Warrants granted", "100", "5.00"),
            ("Warrants exercised", "10", "5.00"),
            ("Warrants forfeited", "2", "5.00"),
        ]
    )
    verdict = evaluate_form_test_stock_comp_separator(table, _spec())
    assert verdict.fired and verdict.legs == ("warrant_vocab",)


def test_available_pool_fires_on_an_admitted_geometry():
    table = _table(
        [
            ("Available for issuance", "500"),
            ("Granted", "100"),
            ("Expired", "10"),
            ("Forfeited", "5"),
        ]
    )
    verdict = evaluate_form_test_stock_comp_separator(table, _spec())
    assert verdict.fired and verdict.legs == ("available_pool",)


def test_seat_bound_holds_under_the_range_shape_exception():
    # Price-form grid whose column heads carry no exercise-price
    # term: range-bucket stubs over outstanding/exercisable
    # columns except the claim on their own shape (W1).
    table = _table(
        [
            ("Exercise price range", "Shares outstanding", "Shares exercisable"),
            ("$0.01 - $5.00", "100", "50"),
            ("$5.01 - $10.00", "200", "80"),
            ("$10.01 and above", "50", "20"),
        ]
    )
    surfaces = StockCompSeparatorText.from_table(table).surfaces
    assert surfaces is not None
    assert surfaces.range_rows >= 2 and surfaces.col_out and surfaces.col_exerc
    assert not surfaces.col_waep and not surfaces.seat_admitted
    verdict = evaluate_form_test_stock_comp_separator(table, _spec())
    assert not verdict.fired and verdict.legs == ()


def test_seat_bound_holds_under_the_core_exception():
    # A walk the legs read whole (bookends + activity = core)
    # whose derived seat form fails on the exercisable column:
    # the core excepts the claim from seat_bound (W2).
    table = _table(
        [
            ("", "Shares", "Shares exercisable"),
            ("Balance, beginning of year", "100", "40"),
            ("Granted", "10", "0"),
            ("Exercised", "(5)", "0"),
            ("Forfeited", "(2)", "0"),
            ("Balance, end of year", "103", "45"),
        ]
    )
    surfaces = StockCompSeparatorText.from_table(table).surfaces
    assert surfaces is not None
    assert surfaces.core and not surfaces.seat_admitted
    assert not surfaces.bookend and not surfaces.col_waep
    verdict = evaluate_form_test_stock_comp_separator(table, _spec())
    assert not verdict.fired and verdict.legs == ()


def test_available_pool_silent_on_an_admitted_core_geometry():
    # The available read fires on an admitted geometry only
    # when its legs lack the core (W3).
    table = _table(
        [
            ("Balance, beginning of year", "100"),
            ("Granted", "10"),
            ("Exercised", "(5)"),
            ("Available for issuance", "500"),
            ("Balance, end of year", "105"),
        ]
    )
    surfaces = StockCompSeparatorText.from_table(table).surfaces
    assert surfaces is not None
    assert surfaces.seat_admitted and surfaces.core and surfaces.available
    verdict = evaluate_form_test_stock_comp_separator(table, _spec())
    assert not verdict.fired and verdict.legs == ()


def test_span_silent_on_an_admitted_core_geometry():
    # Five year columns over an admitted core walk: the span
    # leg stays silent (W5).
    table = _table(
        [
            ("", "2019", "2020", "2021", "2022", "2023"),
            ("Balance, beginning of year", "100", "100", "100", "100", "100"),
            ("Granted", "10", "10", "10", "10", "10"),
            ("Exercised", "(5)", "(5)", "(5)", "(5)", "(5)"),
            ("Balance, end of year", "105", "105", "105", "105", "105"),
        ]
    )
    surfaces = StockCompSeparatorText.from_table(table).surfaces
    assert surfaces is not None
    assert surfaces.seat_admitted and surfaces.core
    verdict = evaluate_form_test_stock_comp_separator(table, _spec())
    assert not verdict.fired and verdict.legs == ()


def test_warrant_vocab_ignores_lead_and_caption_vocabulary():
    # "Warrant" named only in the caption: the warrant read
    # runs over stubs + headers, so the leg stays silent (W4b).
    geometry = TableGeometry(
        table_index=0,
        render_result=TableRenderResult(
            ascii_text="",
            resolved_grid=ResolvedGrid(
                rows=[
                    ("Options granted", "100"),
                    ("Options exercised", "10"),
                    ("Options forfeited", "2"),
                ],
                column_alignments=(),
                column_widths=(),
                header_row_count=0,
            ),
            confidence=1.0,
        ),
    )
    context = TableContext(
        geometry=geometry, caption_stack=("Warrant activity",), prose_before=""
    )
    table = structure_table(context)
    surfaces = StockCompSeparatorText.from_table(table).surfaces
    assert surfaces is not None and not surfaces.warrant
    verdict = evaluate_form_test_stock_comp_separator(table, _spec())
    assert "warrant_vocab" not in verdict.legs


def test_c2_legs_stay_silent_on_a_grid_only_text():
    # No typed table, no surfaces: warrant vocabulary in the
    # grid alone never fires the claim-local C2 legs.
    text = StockCompSeparatorText("Warrants granted | 100\nWarrants exercised | 10")
    verdict = evaluate_stock_comp_separator(text, SPEC)
    assert not verdict.fired


# ---------------- stage adapter + dispatch ----------------


def _table(rows):
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
    context = TableContext(geometry=geometry, caption_stack=(), prose_before="")
    return structure_table(context)


def test_stage_adapter_over_full_grid():
    table = _table(
        (("Options granted", "2011", "2012", "2013", "2016", "2017", "2018"),)
    )
    spec = next(s for s in FORM_TEST_SPECS if s.test_id == "stock_comp_separator")
    verdict = evaluate_form_test_stock_comp_separator(table, spec)
    assert verdict.fired
    assert "span_ge_5" in verdict.legs


def test_stage_dispatch_stamps_separator_outcome():
    table = _table(
        (("Options granted", "2011", "2012", "2013", "2016", "2017", "2018"),)
    )
    outcomes = {o.test_id: o for o in evaluate_form_tests(table)}
    outcome = outcomes["stock_comp_separator"]
    assert outcome.kind == TEST_STOCK_COMP_SEPARATOR
    assert not outcome.passed and outcome.evaluable
    assert outcome.points == 0.0


# ---------------- competition gate ----------------

_SCORE = {FAMILY: FamilyScore(FAMILY, 11.0, {"signature": 11.0}, ())}


def _outcome(passed: bool, evaluable: bool = True) -> FormTestOutcome:
    return FormTestOutcome(
        FAMILY,
        "stock_comp_separator",
        TEST_STOCK_COMP_SEPARATOR,
        passed,
        evaluable,
        0,
        0.0,
        "separator fired: span_ge_5",
    )


def test_gate_removes_claim_on_fired_outcome():
    geometry = GeometryText(form_tests=(_outcome(False),))
    result = compete(geometry, scores=dict(_SCORE))
    assert FAMILY not in result.claims
    evidence = result.scores[FAMILY].evidence
    assert any(
        item.channel == "gate" and "separator fired" in item.detail for item in evidence
    )


def test_gate_keeps_claim_on_clear_outcome():
    geometry = GeometryText(form_tests=(_outcome(True),))
    result = compete(geometry, scores=dict(_SCORE))
    assert FAMILY in result.claims


def test_gate_keeps_claim_when_outcome_absent():
    result = compete(GeometryText(), scores=dict(_SCORE))
    assert FAMILY in result.claims


def test_gate_keeps_claim_when_outcome_unevaluable():
    geometry = GeometryText(form_tests=(_outcome(False, evaluable=False),))
    result = compete(geometry, scores=dict(_SCORE))
    assert FAMILY in result.claims


# ---------------- assignment pass ----------------


def _result(*families):
    scores = {
        family: FamilyScore(family, 11.0, {"signature": 11.0}, ())
        for family in families
    }
    return CompetitionResult(claims=families, contested=(), scores=scores)


_ADMITTING_GRID = (
    "Expected volatility | risk-free interest rate | dividend yield | expected term"
)
_QUIET_GRID = "Weighted average exercise price | 10.50"


def test_assignment_refuses_when_anchor_seat_admits():
    results = apply_stock_comp_assignment(
        [GeometryText(grid_text=_ADMITTING_GRID)],
        [_result(FAMILY, ANCHOR)],
    )
    assert FAMILY not in results[0].claims
    assert ANCHOR in results[0].claims
    evidence = results[0].scores[FAMILY].evidence
    assert any(
        item.channel == "gate" and "stock comp assignment" in item.detail
        for item in evidence
    )


def test_assignment_keeps_claim_when_anchor_seat_silent():
    results = apply_stock_comp_assignment(
        [GeometryText(grid_text=_QUIET_GRID)],
        [_result(FAMILY, ANCHOR)],
    )
    assert FAMILY in results[0].claims
    assert ANCHOR in results[0].claims


def test_assignment_keeps_claim_without_anchor_claim():
    results = apply_stock_comp_assignment(
        [GeometryText(grid_text=_ADMITTING_GRID)],
        [_result(FAMILY)],
    )
    assert FAMILY in results[0].claims


def test_assignment_preserves_cross_claims():
    results = apply_stock_comp_assignment(
        [GeometryText(grid_text=_ADMITTING_GRID)],
        [_result(FAMILY, ANCHOR, "balance_sheet")],
    )
    assert FAMILY not in results[0].claims
    assert ANCHOR in results[0].claims
    assert "balance_sheet" in results[0].claims


def test_assignment_leaves_other_families_alone():
    results = apply_stock_comp_assignment(
        [
            GeometryText(grid_text=_ADMITTING_GRID),
            GeometryText(grid_text=_ADMITTING_GRID),
        ],
        [_result(ANCHOR), _result("balance_sheet")],
    )
    assert ANCHOR in results[0].claims
    assert "balance_sheet" in results[1].claims
