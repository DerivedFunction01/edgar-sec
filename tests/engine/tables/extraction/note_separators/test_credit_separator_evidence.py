"""Credit separator (TEST_CREDIT_SEPARATOR): legs, gate."""

from __future__ import annotations

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
from edgar_sec.engine.tables.extraction.note_separators.credit_separator_evidence import (
    CreditSeparatorText,
    evaluate_credit_separator,
    evaluate_form_test_credit_separator,
)
from edgar_sec.engine.tables.extraction.note_separators.credit_separator_specs import (
    CREDIT_SEPARATOR_SPECS,
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
from edgar_sec.engine.tables.extraction.core.subjects.profiles import (
    PROV_CREDIT_SEPARATOR,
    TEST_CREDIT_SEPARATOR,
    profile_for,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import structure_table

SPEC = CREDIT_SEPARATOR_SPECS["credit_losses_rollforward"]
FAMILY = "credit_losses_rollforward"


def _eval(table_text: str):
    return evaluate_credit_separator(CreditSeparatorText((), table_text), SPEC)


def test_kind_is_declared_as_form_test_data():
    entry = next(
        s
        for s in FORM_TEST_SPECS
        if s.family == FAMILY and s.kind == TEST_CREDIT_SEPARATOR
    )
    assert entry.test_id == "credit_separator"
    assert entry.points == 0.0
    assert entry.provenance == PROV_CREDIT_SEPARATOR
    assert SPEC.family == FAMILY
    assert TEST_CREDIT_SEPARATOR in profile_for(FAMILY).form_tests


def test_packet_and_rows_surfaces_agree():
    rows = (
        ("Provision for credit losses", "100"),
        ("Recoveries", "2"),
        ("Loans originated", "50"),
    )
    via_rows = evaluate_credit_separator(CreditSeparatorText.from_rows(rows), SPEC)
    via_packet = evaluate_credit_separator(
        CreditSeparatorText.from_packet(
            {
                "table_text": "Provision for credit losses|100\n"
                "Recoveries|2\n"
                "Loans originated|50"
            }
        ),
        SPEC,
    )
    assert via_rows == via_packet


# ---------------- the claim-local legs ----------------


def test_leg_movement_count_fires_below_two_kinds():
    verdict = _eval(
        "Allowance for credit losses | \n"
        "Provision for credit losses | 100\n"
        "Balance at end of period | 100"
    )
    assert verdict.legs == ("movement_count",)


def test_leg_movement_count_clear_with_two_kinds():
    verdict = _eval(
        "Provision for credit losses | 100\n"
        "Recoveries of amounts previously charged off | 5\n"
        "Balance at end of period | 105"
    )
    assert not verdict.fired
    assert verdict.legs == ()


def test_leg_loan_movement_fires_without_allowance_bookend():
    verdict = _eval(
        "Loans originated during the period | 100\n"
        "Provision for credit losses | 10\n"
        "Recoveries | 2"
    )
    assert verdict.legs == ("loan_movement",)


def test_leg_loan_movement_clear_with_allowance_bookend():
    verdict = _eval(
        "Allowance for loan losses, beginning balance | 90\n"
        "Loans originated during the period | 100\n"
        "Provision for credit losses | 10\n"
        "Recoveries | 2"
    )
    assert not verdict.fired
    assert verdict.legs == ()


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
    table = _table((("Provision for credit losses", "100"), ("Balance", "50")))
    spec = next(s for s in FORM_TEST_SPECS if s.test_id == "credit_separator")
    verdict = evaluate_form_test_credit_separator(table, spec)
    assert verdict.fired
    assert "movement_count" in verdict.legs


def test_stage_dispatch_stamps_separator_outcome():
    table = _table((("Provision for credit losses", "100"), ("Balance", "50")))
    outcomes = {o.test_id: o for o in evaluate_form_tests(table)}
    outcome = outcomes["credit_separator"]
    assert outcome.kind == TEST_CREDIT_SEPARATOR
    assert not outcome.passed and outcome.evaluable
    assert outcome.points == 0.0


# ---------------- competition gate ----------------

_SCORE = {FAMILY: FamilyScore(FAMILY, 11.0, {"signature": 11.0}, ())}


def _outcome(passed: bool, evaluable: bool = True) -> FormTestOutcome:
    return FormTestOutcome(
        FAMILY,
        "credit_separator",
        TEST_CREDIT_SEPARATOR,
        passed,
        evaluable,
        0,
        0.0,
        "separator fired: movement_count",
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


# ---------------- spec leg set ----------------


def test_spec_carries_the_ruled_leg_set():
    legs = [(leg.leg_id, leg.scope) for leg in SPEC.legs]
    assert legs == [
        ("movement_count", "claim-local"),
        ("loan_movement", "claim-local"),
    ]
