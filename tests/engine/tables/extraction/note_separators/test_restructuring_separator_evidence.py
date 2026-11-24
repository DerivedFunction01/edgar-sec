"""Restructuring separator (TEST_RESTRUCTURING_SEPARATOR): legs, gate."""

from __future__ import annotations

import edgar_sec.engine.tables.extraction.note_separators.restructuring_separator_evidence as _rse
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
    FamilyScore,
)
from edgar_sec.engine.tables.extraction.core.subjects.profile_constants import (
    PROV_RESTRUCTURING_SEPARATOR,
    TEST_RESTRUCTURING_SEPARATOR,
)
from edgar_sec.engine.tables.extraction.core.subjects.profiles import (
    profile_for,
)
from edgar_sec.engine.tables.extraction.note_separators.restructuring_separator_evidence import (
    evaluate_form_test_restructuring_separator,
    evaluate_restructuring_separator,
)
from edgar_sec.engine.tables.extraction.note_separators.restructuring_separator_specs import (
    RESTRUCTURING_SEPARATOR_SPECS,
)
from edgar_sec.engine.tables.extraction.evidence.rollforward_grid_evidence import (
    RollforwardGridText,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import structure_table

SPEC = RESTRUCTURING_SEPARATOR_SPECS["restructuring"]
FAMILY = "restructuring"


def _eval(table_text: str):
    return evaluate_restructuring_separator(RollforwardGridText(table_text), SPEC)


def test_kind_is_declared_as_form_test_data():
    entry = next(
        s
        for s in FORM_TEST_SPECS
        if s.family == FAMILY and s.kind == TEST_RESTRUCTURING_SEPARATOR
    )
    assert entry.test_id == "restructuring_separator"
    assert entry.points == 0.0
    assert entry.provenance == PROV_RESTRUCTURING_SEPARATOR
    assert SPEC.family == FAMILY
    assert TEST_RESTRUCTURING_SEPARATOR in profile_for(FAMILY).form_tests


def test_spec_carries_the_priced_pair():
    legs = [(leg.leg_id, leg.kind, leg.scope) for leg in SPEC.legs]
    assert legs == [
        ("nb_span_ge3", "no_bookend_span", "claim-local"),
        ("restr_zeroact", "zero_activity", "claim-local"),
    ]
    span = next(leg for leg in SPEC.legs if leg.kind == "no_bookend_span")
    assert span.limit == 3


def test_packet_and_rows_surfaces_agree():
    rows = (
        ("Payments", "2019", "2020", "2021"),
        ("Lease termination", "10", "20", "30"),
    )
    via_rows = evaluate_restructuring_separator(
        RollforwardGridText.from_rows(rows), SPEC
    )
    via_packet = evaluate_restructuring_separator(
        RollforwardGridText.from_packet(
            {
                "table_text": "Payments | 2019 | 2020 | 2021\n"
                "Lease termination | 10 | 20 | 30"
            }
        ),
        SPEC,
    )
    assert via_rows == via_packet
    assert via_rows.fired


def test_recognizer_homes():
    assert _rse.fired_separator_outcome is _CORE_FORM_OUTCOME


# ---------------- the claim-local legs ----------------

_MATRIX = "Payments | 2019 | 2020 | 2021\nLease termination | 10 | 20 | 30"


def test_leg_nb_span_ge3_fires_on_bookend_free_span():
    verdict = _eval(_MATRIX)
    assert verdict.fired
    assert verdict.legs == ("nb_span_ge3",)


def test_leg_nb_span_ge3_fires_at_the_boundary():
    verdict = _eval("Payments | 2022 | 2023 | 2024\nCharges | 1 | 2 | 3")
    assert verdict.legs == ("nb_span_ge3",)


def test_leg_nb_span_clear_below_three_years():
    verdict = _eval("Payments | 2023 | 2024\nCharges | 1 | 2")
    assert not verdict.fired


def test_leg_nb_span_blocked_by_a_bookend():
    text = (
        "Balance at January 1, 2019 | 100\n"
        "Charges | 5\n"
        "Balance at December 31, 2021 | 105"
    )
    verdict = _eval(text)
    assert "nb_span_ge3" not in verdict.legs


_ZERO_WALK = (
    "Balance, beginning of period | 0\n"
    "Charges | 0\n"
    "Payments | 0\n"
    "Balance, end of period | 0"
)


def test_leg_zeroact_fires_on_an_unchanged_silent_walk():
    verdict = _eval(_ZERO_WALK)
    assert verdict.fired
    assert verdict.legs == ("restr_zeroact",)


def test_leg_zeroact_clear_with_nonzero_movement():
    verdict = _eval(_ZERO_WALK.replace("Charges | 0", "Charges | 5"))
    assert not verdict.fired


def test_leg_zeroact_clear_when_balances_change():
    verdict = _eval(_ZERO_WALK.replace("end of period | 0", "end of period | 90"))
    assert not verdict.fired


def test_empty_grid_is_unevaluable():
    verdict = _eval("")
    assert not verdict.fired
    assert not verdict.evaluable


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
    table = _table((("Payments", "2019", "2020", "2021"), ("Charges", "1", "2", "3")))
    spec = next(s for s in FORM_TEST_SPECS if s.test_id == "restructuring_separator")
    verdict = evaluate_form_test_restructuring_separator(table, spec)
    assert verdict.fired
    assert "nb_span_ge3" in verdict.legs


def test_stage_dispatch_stamps_separator_outcome():
    table = _table((("Payments", "2019", "2020", "2021"), ("Charges", "1", "2", "3")))
    outcomes = {o.test_id: o for o in evaluate_form_tests(table)}
    outcome = outcomes["restructuring_separator"]
    assert outcome.kind == TEST_RESTRUCTURING_SEPARATOR
    assert not outcome.passed and outcome.evaluable
    assert outcome.points == 0.0


# ---------------- competition gate ----------------

_SCORE = {FAMILY: FamilyScore(FAMILY, 11.0, {"signature": 11.0}, ())}


def _outcome(passed: bool, evaluable: bool = True) -> FormTestOutcome:
    return FormTestOutcome(
        FAMILY,
        "restructuring_separator",
        TEST_RESTRUCTURING_SEPARATOR,
        passed,
        evaluable,
        0,
        0.0,
        "separator fired: nb_span_ge3",
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
