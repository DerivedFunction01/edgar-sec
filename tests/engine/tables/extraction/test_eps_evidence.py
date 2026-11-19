"""EPS seat kind: the priced rule's specimen shapes.
Pins transcribe the priced leg definitions and the
transfer-pricing remedies (caption title, signed walk, gate).
"""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.competition import GeometryText, compete
from edgar_sec.engine.tables.extraction.context import TableContext
from edgar_sec.engine.tables.extraction.eps_evidence import (
    EpsText,
    evaluate_form_test_eps_detector,
    legs_for,
)
from edgar_sec.engine.tables.extraction.eps_specs import EPS_EVIDENCE_SPECS
from edgar_sec.engine.tables.extraction.form_test_specs import (
    FORM_TEST_SPECS,
    FormTestOutcome,
)
from edgar_sec.engine.tables.extraction.form_tests import evaluate_form_tests
from edgar_sec.engine.tables.extraction.geometry_scoring import FamilyScore
from edgar_sec.engine.tables.extraction.profiles import TEST_EPS_DETECTOR, profile_for
from edgar_sec.engine.tables.extraction.typed_rows import TypedTable, structure_table

TEST_ID = "eps_evidence"
DETECTOR_ID = "eps_detector"
SPEC = EPS_EVIDENCE_SPECS["eps_reconciliation"]


def _table(
    rows: tuple[tuple[str, ...], ...],
    *,
    caption_stack: tuple[str, ...] = (),
    prose_before: str = "",
) -> TypedTable:
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
    context = TableContext(
        geometry=geometry, caption_stack=caption_stack, prose_before=prose_before
    )
    return structure_table(context)


def _outcome(table: TypedTable):
    return next(o for o in evaluate_form_tests(table) if o.test_id == TEST_ID)


def _legs(table: TypedTable):
    return legs_for(EpsText.from_table(table), SPEC)


def test_pair_form_seats_with_detector_silent() -> None:
    table = _table(
        (
            ("Basic earnings per share", "1.00"),
            ("Diluted earnings per share", "0.90"),
        ),
        prose_before="Net income per share — basic and diluted — follows.",
    )
    legs = _legs(table)
    assert legs.pair and legs.h1 and not legs.det
    outcome = _outcome(table)
    assert outcome.passed
    assert outcome.detail == "pair form, detector silent"


def test_denominator_identity_seats_without_the_pair() -> None:
    table = _table(
        (
            ("Basic shares", "10,000", "9,000"),
            ("Dilutive effect of options", "500", "400"),
            ("Diluted shares", "10,500", "9,400"),
        ),
        prose_before="Shares outstanding data follows.",
    )
    legs = _legs(table)
    assert legs.es_add and legs.bd_arm and not legs.pair
    assert not legs.v_signed
    outcome = _outcome(table)
    assert outcome.passed
    assert outcome.detail == "denominator form, detector silent"


def test_signed_treasury_walk_seats_via_v_signed() -> None:
    # R-B (transfer pricing): the treasury-method walk in
    # decimal millions — the repurchase leg subtracts, so the
    # spine's integral scale and the variants' non-negative
    # mids both fail; the signed arm completes the identity.
    table = _table(
        (
            ("Basic weighted average shares outstanding", "2,774.8", "2,700.0"),
            ("Dilutive effect of stock options", "85.0", "80.0"),
            ("Repurchase of common shares", "(42.7)", "(30.0)"),
            ("Diluted weighted average shares outstanding", "2,817.1", "2,750.0"),
        )
    )
    legs = _legs(table)
    assert legs.v_signed and legs.bd_arm and legs.h1 and not legs.det
    assert not legs.es_add and not legs.v_any and not legs.w_any
    outcome = _outcome(table)
    assert outcome.passed
    assert outcome.detail == "denominator form, detector silent"


def test_bridge_form_seats_without_basic_vocabulary() -> None:
    # The depth-2 :24 shape: a weighted-average bridge whose
    # stubs never say "basic", claimed by the W legs alone.
    table = _table(
        (
            ("Weighted average shares outstanding", "24,322,264", "20,000,000"),
            ("Dilutive effect of stock plans", "257,126", "100,000"),
            ("Diluted weighted average shares outstanding", "24,579,390", "20,100,000"),
        )
    )
    legs = _legs(table)
    assert legs.w_any and not legs.basic_diluted and not legs.det
    outcome = _outcome(table)
    assert outcome.passed
    assert outcome.detail == "bridge form, detector silent"


def test_combined_basic_and_diluted_row_seats_via_v_comb() -> None:
    table = _table((("Basic and diluted shares outstanding", "50,417", "49,315"),))
    legs = _legs(table)
    assert legs.v_comb and legs.v_any and legs.bd_arm
    assert _outcome(table).passed


def test_zero_effect_equality_seats_via_v_eq() -> None:
    # The depth-2 EQ class: basic and diluted denominators
    # equal, the anti-dilutive presentation.
    table = _table(
        (
            ("Basic shares", "713", "100"),
            ("Diluted shares", "713", "100"),
        )
    )
    legs = _legs(table)
    assert legs.v_eq and legs.v_eqx and not legs.es_add
    assert _outcome(table).passed


def test_operating_walk_grid_is_screened_by_det_walk3() -> None:
    # The depth-3 FP shape: an income-statement walk whose
    # per-share foot the pair reaches; the detector screens it.
    table = _table(
        (
            ("Revenue", "100"),
            ("Cost of revenue", "40"),
            ("Gross profit", "60"),
            ("Basic earnings per share", "1.00"),
            ("Diluted earnings per share", "0.90"),
        ),
        prose_before="Earnings per share — basic and diluted — are computed.",
    )
    legs = _legs(table)
    assert legs.pair and legs.h1 and legs.det_walk3 and legs.det
    outcome = _outcome(table)
    assert not outcome.passed
    assert outcome.detail == "detector screens the union form"


def test_terminal_per_share_foot_is_screened_by_det_foot60() -> None:
    table = _table(
        (
            ("Widgets", "10"),
            ("Gadgets", "20"),
            ("Gizmos", "30"),
            ("Basic per share", "1.0"),
            ("Diluted per share", "0.9"),
        ),
        prose_before="Per share amounts — basic and diluted — follow.",
    )
    legs = _legs(table)
    assert legs.pair and legs.det_foot60 and not legs.det_walk3
    assert legs.anatomy_first_fraction == 0.6
    assert not _outcome(table).passed


def test_statement_title_in_the_lead_no_longer_screens() -> None:
    # R-A (transfer pricing): title evidence binds on the
    # geometry's own caption; an EPS note's prose referring
    # to the statement of operations is the disclosure's own
    # cross-reference, not a primary-statement screen.
    table = _table(
        (
            ("Basic shares", "10,000", "9,000"),
            ("Diluted shares", "10,500", "9,400"),
        ),
        prose_before="The statements of operations include basic and diluted amounts.",
    )
    legs = _legs(table)
    assert legs.pair and not legs.det_title and not legs.det
    assert _outcome(table).passed


def test_statement_title_in_the_caption_is_screened_by_det_title() -> None:
    table = _table(
        (
            ("Basic shares", "10,000", "9,000"),
            ("Diluted shares", "10,500", "9,400"),
        ),
        caption_stack=("Consolidated Statements of Operations",),
        prose_before="Basic and diluted amounts follow.",
    )
    legs = _legs(table)
    assert legs.pair and legs.det_title and legs.det
    assert not _outcome(table).passed


def test_plain_grid_without_vocabulary_has_no_seat_leg() -> None:
    table = _table((("Apples", "10"), ("Oranges", "20")))
    legs = _legs(table)
    assert not legs.h1 and not legs.det and not legs.claim
    outcome = _outcome(table)
    assert not outcome.passed
    assert outcome.detail == "no seat leg"


def test_outcome_carries_the_seat_kind_and_points() -> None:
    outcome = _outcome(
        _table(
            (
                ("Basic earnings per share", "1.00"),
                ("Diluted earnings per share", "0.90"),
            ),
            prose_before="Net income per share — basic and diluted — follows.",
        )
    )
    assert outcome.family == "eps_reconciliation"
    assert outcome.kind == "eps_evidence"
    assert outcome.points == 3.0
    assert outcome.evaluable


def test_spec_carries_the_priced_thresholds() -> None:
    assert SPEC.foot_threshold == 60
    assert SPEC.walk_min_rows == 3
    assert SPEC.lead_term == "basic and"


def test_empty_grid_is_unevaluable() -> None:
    outcome = _outcome(_table(()))
    assert not outcome.passed
    assert not outcome.evaluable
    assert outcome.detail == "no grid rows"


# ---------------- detector kind (R-D gate evidence) ----------------


def _detector_outcome(table: TypedTable):
    return next(o for o in evaluate_form_tests(table) if o.test_id == DETECTOR_ID)


def test_detector_kind_is_declared_on_the_profile() -> None:
    profile = profile_for("eps_reconciliation")
    assert profile is not None and TEST_EPS_DETECTOR in profile.form_tests
    spec = next(s for s in FORM_TEST_SPECS if s.test_id == DETECTOR_ID)
    assert spec.kind == TEST_EPS_DETECTOR and spec.points == 0.0


def test_detector_silent_on_a_seat_grid() -> None:
    table = _table(
        (
            ("Basic earnings per share", "1.00"),
            ("Diluted earnings per share", "0.90"),
        ),
        prose_before="Net income per share — basic and diluted — follows.",
    )
    outcome = _detector_outcome(table)
    assert outcome.passed and outcome.evaluable
    assert outcome.detail == "detector silent"


def test_detector_fires_on_a_caption_title_grid() -> None:
    table = _table(
        (
            ("Basic shares", "10,000", "9,000"),
            ("Diluted shares", "10,500", "9,400"),
        ),
        caption_stack=("Consolidated Statements of Operations",),
    )
    spec = next(s for s in FORM_TEST_SPECS if s.test_id == DETECTOR_ID)
    verdict = evaluate_form_test_eps_detector(table, spec)
    assert verdict.fired and verdict.detail == "detector fired: det_title"
    outcome = _detector_outcome(table)
    assert not outcome.passed and outcome.evaluable


def test_detector_empty_grid_is_unevaluable() -> None:
    outcome = _detector_outcome(_table(()))
    assert not outcome.passed and not outcome.evaluable
    assert outcome.detail == "no grid rows"


# ---------------- competition gate (R-D) ----------------

_SCORE = {
    "eps_reconciliation": FamilyScore(
        "eps_reconciliation", 11.0, {"signature": 11.0}, ()
    )
}


def _gate_outcome(passed: bool, evaluable: bool = True) -> FormTestOutcome:
    return FormTestOutcome(
        "eps_reconciliation",
        DETECTOR_ID,
        TEST_EPS_DETECTOR,
        passed,
        evaluable,
        0,
        0.0,
        "detector fired: det_title",
    )


def test_gate_removes_claim_on_fired_outcome() -> None:
    geometry = GeometryText(form_tests=(_gate_outcome(False),))
    result = compete(geometry, scores=dict(_SCORE))
    assert "eps_reconciliation" not in result.claims
    evidence = result.scores["eps_reconciliation"].evidence
    assert any(
        item.channel == "gate" and "detector fired" in item.detail for item in evidence
    )


def test_gate_keeps_claim_on_clear_outcome() -> None:
    geometry = GeometryText(form_tests=(_gate_outcome(True),))
    result = compete(geometry, scores=dict(_SCORE))
    assert "eps_reconciliation" in result.claims


def test_gate_keeps_claim_when_outcome_absent() -> None:
    result = compete(GeometryText(), scores=dict(_SCORE))
    assert "eps_reconciliation" in result.claims


def test_gate_keeps_claim_when_outcome_unevaluable() -> None:
    geometry = GeometryText(form_tests=(_gate_outcome(False, evaluable=False),))
    result = compete(geometry, scores=dict(_SCORE))
    assert "eps_reconciliation" in result.claims
