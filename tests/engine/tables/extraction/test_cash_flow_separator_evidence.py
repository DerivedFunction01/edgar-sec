"""Cash-flow cascade (TEST_CASH_FLOW_SEPARATOR): legs, gate, assignment."""

from __future__ import annotations

import edgar_sec.engine.tables.extraction.cash_flow_separator_evidence as _cfe
from edgar_sec.engine.tables.ascii_html.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.cash_flow_separator_evidence import (
    CashFlowSeparatorText,
    apply_cash_flow_assignment,
    evaluate_cash_flow_separator,
    evaluate_form_test_cash_flow_separator,
    stub_key,
)
from edgar_sec.engine.tables.extraction.cash_flow_separator_specs import (
    CASH_FLOW_SEPARATOR_SPECS,
)
from edgar_sec.engine.tables.extraction.competition import (
    CompetitionResult,
    GeometryText,
    compete,
)
from edgar_sec.engine.tables.extraction.context import TableContext
from edgar_sec.engine.tables.extraction.form_test_specs import FORM_TEST_SPECS
from edgar_sec.engine.tables.extraction.form_tests import (
    FormTestOutcome,
    evaluate_form_tests,
)
from edgar_sec.engine.tables.extraction.geometry_scoring import FamilyScore
from edgar_sec.engine.tables.extraction.pension_routed_evidence import (
    norm as _PENSION_NORM,
    stub_key as _PENSION_STUB_KEY,
)
from edgar_sec.engine.tables.extraction.primary_gate import (
    section_presence as _HOME_SECTION_PRESENCE,
)
from edgar_sec.engine.tables.extraction.profiles import (
    PROV_CASH_FLOW_CASCADE,
    TEST_CASH_FLOW_SEPARATOR,
    profile_for,
)
from edgar_sec.engine.tables.extraction.typed_rows import structure_table

SPEC = CASH_FLOW_SEPARATOR_SPECS["cash_flow"]

_RECONCILIATION = "Net increase in cash and cash equivalents | 10 | 5"


def _eval(table_text: str):
    return evaluate_cash_flow_separator(CashFlowSeparatorText(table_text), SPEC)


def _statement(rows: int, header: str = " | 2024 | 2023") -> str:
    body = [f"Operating item {i} | 100 | 200" for i in range(rows)]
    return "\n".join([header, *body, _RECONCILIATION])


def test_kind_is_declared_as_form_test_data():
    entry = next(
        s
        for s in FORM_TEST_SPECS
        if s.family == "cash_flow" and s.kind == TEST_CASH_FLOW_SEPARATOR
    )
    assert entry.test_id == "cash_flow_separator"
    assert entry.points == 0.0
    assert entry.provenance == PROV_CASH_FLOW_CASCADE
    assert SPEC.family == "cash_flow"
    assert SPEC.core_section == "cash_reconciliation"
    assert TEST_CASH_FLOW_SEPARATOR in profile_for("cash_flow").form_tests


def test_packet_and_rows_surfaces_agree():
    rows = (
        ("Net cash provided by operating activities", "100"),
        ("Net increase in cash and cash equivalents", "10"),
    )
    via_rows = evaluate_cash_flow_separator(CashFlowSeparatorText.from_rows(rows), SPEC)
    via_packet = evaluate_cash_flow_separator(
        CashFlowSeparatorText.from_packet(
            {
                "table_text": "Net cash provided by operating activities | 100\n"
                "Net increase in cash and cash equivalents | 10"
            }
        ),
        SPEC,
    )
    assert via_rows == via_packet


def test_recognizer_homes():
    assert _cfe.stub_key is _PENSION_STUB_KEY
    assert _cfe.token_norm is _PENSION_NORM
    assert _cfe.section_presence is _HOME_SECTION_PRESENCE
    assert stub_key("Cash, beginning of period") == "cash beginning of period"


# ---------------- the claim-local legs ----------------


def test_leg_rows_le_12():
    verdict = _eval(_statement(4))
    assert verdict.legs == ("rows_le_12",)


def test_leg_header_value():
    verdict = _eval(_statement(14, header="Item | Value | 2023"))
    assert verdict.legs == ("hdr:value",)


def test_leg_core_absent():
    lines = [" | 2024 | 2023"] + [f"Operating item {i} | 1 | 2" for i in range(14)]
    verdict = _eval("\n".join(lines))
    assert verdict.legs == ("core_absent:cash_reconciliation",)


def test_plain_cash_flow_statement_is_clear():
    lines = [
        " | 2024 | 2023",
        "Net income | 500 | 450",
        "Depreciation and amortization | 60 | 55",
        "Changes in operating assets and liabilities | 20 | 15",
        "Net cash provided by operating activities | 580 | 520",
        "Capital expenditures | (200) | (180)",
        "Acquisitions | (50) | 0",
        "Net cash used in investing activities | (250) | (180)",
        "Proceeds from debt | 100 | 90",
        "Repayments of debt | (80) | (70)",
        "Dividends paid | (30) | (25)",
        "Net cash used in financing activities | (10) | (5)",
        "Net increase in cash and cash equivalents | 320 | 335",
        "Cash and cash equivalents, beginning of period | 400 | 65",
        "Cash and cash equivalents, end of period | 720 | 400",
    ]
    verdict = _eval("\n".join(lines))
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
    table = _table((("Cash", "100"), ("Total assets", "50")))
    spec = next(s for s in FORM_TEST_SPECS if s.test_id == "cash_flow_separator")
    verdict = evaluate_form_test_cash_flow_separator(table, spec)
    assert verdict.fired
    assert "rows_le_12" in verdict.legs


def test_stage_dispatch_stamps_separator_outcome():
    table = _table((("Cash", "100"), ("Total assets", "50")))
    outcomes = {o.test_id: o for o in evaluate_form_tests(table)}
    outcome = outcomes["cash_flow_separator"]
    assert outcome.kind == TEST_CASH_FLOW_SEPARATOR
    assert not outcome.passed and outcome.evaluable
    assert outcome.points == 0.0


# ---------------- competition gate ----------------

_SCORE = {"cash_flow": FamilyScore("cash_flow", 11.0, {"signature": 11.0}, ())}


def _outcome(passed: bool, evaluable: bool = True) -> FormTestOutcome:
    return FormTestOutcome(
        "cash_flow",
        "cash_flow_separator",
        TEST_CASH_FLOW_SEPARATOR,
        passed,
        evaluable,
        0,
        0.0,
        "separator fired: rows_le_12",
    )


def test_gate_removes_claim_on_fired_outcome():
    geometry = GeometryText(form_tests=(_outcome(False),))
    result = compete(geometry, scores=dict(_SCORE))
    assert "cash_flow" not in result.claims
    evidence = result.scores["cash_flow"].evidence
    assert any(
        item.channel == "gate" and "separator fired" in item.detail for item in evidence
    )


def test_gate_keeps_claim_on_clear_outcome():
    geometry = GeometryText(form_tests=(_outcome(True),))
    result = compete(geometry, scores=dict(_SCORE))
    assert "cash_flow" in result.claims


def test_gate_keeps_claim_when_outcome_absent():
    result = compete(GeometryText(), scores=dict(_SCORE))
    assert "cash_flow" in result.claims


def test_gate_keeps_claim_when_outcome_unevaluable():
    geometry = GeometryText(form_tests=(_outcome(False, evaluable=False),))
    result = compete(geometry, scores=dict(_SCORE))
    assert "cash_flow" in result.claims


# ---------------- assignment pass ----------------


def test_spec_carries_the_ruled_leg_set():
    legs = [(leg.leg_id, leg.scope) for leg in SPEC.legs]
    assert legs == [
        ("rows_le_12", "claim-local"),
        ("hdr:value", "claim-local"),
        ("core_absent:cash_reconciliation", "claim-local"),
        ("winner_take_all", "set-level"),
    ]


def _result(*families):
    scores = {
        family: FamilyScore(family, 11.0, {"signature": 11.0}, ())
        for family in families
    }
    return CompetitionResult(claims=families, contested=(), scores=scores)


def test_assignment_refuses_competing_survivors():
    results = apply_cash_flow_assignment(
        [GeometryText(), GeometryText()],
        [_result("cash_flow"), _result("cash_flow")],
    )
    assert all("cash_flow" not in r.claims for r in results)
    evidence = results[0].scores["cash_flow"].evidence
    assert any(item.channel == "gate" for item in evidence)


def test_assignment_keeps_singleton_claim():
    results = apply_cash_flow_assignment(
        [GeometryText(), GeometryText()],
        [_result("cash_flow"), _result("balance_sheet")],
    )
    assert "cash_flow" in results[0].claims
    assert "balance_sheet" in results[1].claims


def test_assignment_preserves_cross_claims():
    results = apply_cash_flow_assignment(
        [GeometryText(), GeometryText()],
        [_result("cash_flow", "balance_sheet"), _result("cash_flow")],
    )
    assert "cash_flow" not in results[0].claims
    assert "balance_sheet" in results[0].claims


def test_assignment_leaves_other_families_alone():
    results = apply_cash_flow_assignment(
        [GeometryText(), GeometryText()],
        [_result("balance_sheet"), _result("balance_sheet")],
    )
    assert all("balance_sheet" in r.claims for r in results)
