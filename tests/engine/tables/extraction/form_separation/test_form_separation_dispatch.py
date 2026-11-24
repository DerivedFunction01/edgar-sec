"""Form separation: stage dispatch and the competition gate."""

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
from edgar_sec.engine.tables.extraction.form_tests.form_tests import (
    FormTestOutcome,
    evaluate_form_tests,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
    FamilyScore,
)
from edgar_sec.engine.tables.extraction.core.subjects.profile_constants import (
    TEST_FORM_SEPARATION,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import structure_table

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


def test_stage_dispatch_stamps_clear_outcome_on_related_party_grid():
    table = _table(
        (("Due from related parties", "10"), ("Due to related parties", "50"))
    )
    outcomes = {o.test_id: o for o in evaluate_form_tests(table)}
    outcome = outcomes["related_party_form_separation"]
    assert outcome.kind == TEST_FORM_SEPARATION
    assert outcome.passed and outcome.evaluable
    assert outcome.points == 0.0


def test_stage_dispatch_stamps_fired_outcome_on_eps_warrant_grid():
    table = _table(
        (
            ("Common shares purchasable upon exercise of warrants", "10"),
            ("Weighted average exercise price", "5"),
            ("Balance December 31, 2012", "100"),
            ("Exercised", "20"),
        )
    )
    outcomes = {o.test_id: o for o in evaluate_form_tests(table)}
    outcome = outcomes["eps_reconciliation_form_separation"]
    assert outcome.kind == TEST_FORM_SEPARATION
    assert not outcome.passed and outcome.evaluable
    assert outcome.points == 0.0


def test_stage_dispatch_stamps_fired_outcome_on_intangibles_inventory_grid():
    table = _table(
        (
            ("Raw materials", "10"),
            ("Work in process", "5"),
            ("Finished goods", "8"),
            ("Reserve for obsolescence", "(1)"),
        )
    )
    outcomes = {o.test_id: o for o in evaluate_form_tests(table)}
    outcome = outcomes["intangibles_form_separation"]
    assert outcome.kind == TEST_FORM_SEPARATION
    assert not outcome.passed and outcome.evaluable
    assert outcome.points == 0.0


# ---------------- competition gate ----------------

_SCORE = {"related_party": FamilyScore("related_party", 11.0, {"signature": 11.0}, ())}


def _outcome(passed: bool, evaluable: bool = True) -> FormTestOutcome:
    return FormTestOutcome(
        "related_party",
        "related_party_form_separation",
        TEST_FORM_SEPARATION,
        passed,
        evaluable,
        0,
        0.0,
        "form separation fired: form:segment-detail",
    )


def test_gate_removes_claim_on_fired_outcome():
    geometry = GeometryText(form_tests=(_outcome(False),))
    result = compete(geometry, scores=dict(_SCORE))
    assert "related_party" not in result.claims
    evidence = result.scores["related_party"].evidence
    assert any(
        item.channel == "gate" and "form separation fired" in item.detail
        for item in evidence
    )


def test_gate_keeps_claim_on_clear_outcome():
    geometry = GeometryText(form_tests=(_outcome(True),))
    result = compete(geometry, scores=dict(_SCORE))
    assert "related_party" in result.claims


def test_gate_keeps_claim_when_outcome_absent():
    result = compete(GeometryText(), scores=dict(_SCORE))
    assert "related_party" in result.claims


def test_gate_keeps_claim_when_outcome_unevaluable():
    geometry = GeometryText(form_tests=(_outcome(False, evaluable=False),))
    result = compete(geometry, scores=dict(_SCORE))
    assert "related_party" in result.claims
