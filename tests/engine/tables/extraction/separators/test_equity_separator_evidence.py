"""Equity separator (TEST_EQUITY_SEPARATOR): legs, gate, assignment."""

from __future__ import annotations

import edgar_sec.engine.tables.extraction.separators.equity_separator_evidence as _ese
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
from edgar_sec.engine.tables.extraction.separators.equity_separator_evidence import (
    EquitySeparatorText,
    apply_equity_assignment,
    equity_candidate_features,
    evaluate_equity_separator,
    evaluate_form_test_equity_separator,
)
from edgar_sec.engine.tables.extraction.separators.equity_separator_specs import (
    EQUITY_SEPARATOR_SPECS,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_specs import (
    FORM_TEST_SPECS,
)
from edgar_sec.engine.tables.extraction.form_tests.form_tests import (
    FormTestOutcome,
    evaluate_form_tests,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
    CompetitionResult,
    FamilyScore,
)
from edgar_sec.engine.tables.extraction.pension.pension_routed_evidence import (
    header_keys as _PENSION_HEADER_KEYS,
    stub_key as _PENSION_STUB_KEY,
)
from edgar_sec.engine.tables.extraction.pension.pension_routed_specs import (
    HEADER_STOP_TOKENS as _PENSION_STOP_TOKENS,
)
from edgar_sec.engine.tables.extraction.core.subjects.profiles import (
    PROV_COREFIN_EQUITYSTATEMENT,
    TEST_EQUITY_SEPARATOR,
    profile_for,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import structure_table
from edgar_sec.foundation.text.date_patterns import MONTH_NAMES as _HOME_MONTH_NAMES

SPEC = EQUITY_SEPARATOR_SPECS["equity_statement"]

_BALANCE_ROW = "Balance at December 31, 2023 | 500 | 480"
_FILLER = (
    "Common stock | 10 | 10",
    "Additional paid in capital | 200 | 190",
    "Retained earnings | 290 | 270",
    "Common stock issued | 5 | 4",
    "Dividends declared | 8 | 7",
    "Stock based compensation | 12 | 11",
)


def _text(header: str, rows: tuple[str, ...]) -> str:
    return "\n".join([header, *rows])


def _eval(table_text: str):
    return evaluate_equity_separator(EquitySeparatorText(table_text), SPEC)


def test_kind_is_declared_as_form_test_data():
    entry = next(
        s
        for s in FORM_TEST_SPECS
        if s.family == "equity_statement" and s.kind == TEST_EQUITY_SEPARATOR
    )
    assert entry.test_id == "equity_separator"
    assert entry.points == 0.0
    assert entry.provenance == PROV_COREFIN_EQUITYSTATEMENT
    assert SPEC.family == "equity_statement"
    assert TEST_EQUITY_SEPARATOR in profile_for("equity_statement").form_tests


def test_packet_and_rows_surfaces_agree():
    rows = (
        ("Balance at December 31, 2023", "500"),
        ("Common stock", "10"),
    )
    via_rows = evaluate_equity_separator(EquitySeparatorText.from_rows(rows), SPEC)
    via_packet = evaluate_equity_separator(
        EquitySeparatorText.from_packet(
            {"table_text": "Balance at December 31, 2023 | 500\nCommon stock | 10"}
        ),
        SPEC,
    )
    assert via_rows == via_packet


def test_recognizer_homes():
    assert _ese.stub_key is _PENSION_STUB_KEY
    assert _ese.header_keys is _PENSION_HEADER_KEYS
    assert _ese.HEADER_STOP_TOKENS is _PENSION_STOP_TOKENS
    assert _ese.MONTH_NAMES is _HOME_MONTH_NAMES
    assert _ese._YEAR_RE.pattern == r"\b(?:19|20)\d{2}\b"


# ---------------- the claim-local legs ----------------


def test_leg_rows_le_5():
    text = _text("Item | 2024 | 2023", (_BALANCE_ROW, *_FILLER[:3]))
    assert _eval(text).legs == ("rows_le_5",)


def test_leg_span_ge_3():
    text = _text(" | 2023 | 2022 | 2021", (_BALANCE_ROW, *_FILLER))
    assert _eval(text).legs == ("span_ge_3",)


def test_leg_core_gate_without_dated_balance():
    text = _text("Item | 2024 | 2023", _FILLER)
    assert _eval(text).legs == ("core_gate",)


def test_leg_core_gate_balance_without_date_is_not_core():
    rows = ("Balance carried forward | 500 | 480", *_FILLER)
    assert _eval(_text("Item | 2024 | 2023", rows)).legs == ("core_gate",)


def test_leg_stub_total():
    rows = (_BALANCE_ROW, "Total | 900 | 850", *_FILLER[:4])
    assert _eval(_text("Item | 2024 | 2023", rows)).legs == ("stub:total",)


def test_leg_stub_average_shares_dilution():
    rows = (
        _BALANCE_ROW,
        "Average common shares outstanding assuming dilution | 900 | 850",
        *_FILLER[:4],
    )
    text = _text("Item | 2024 | 2023", rows)
    assert _eval(text).legs == (
        "stub:average common shares outstanding assuming dilution",
    )


def test_leg_stub_current_liabilities():
    rows = (_BALANCE_ROW, "Current liabilities | 900 | 850", *_FILLER[:4])
    text = _text("Item | 2024 | 2023", rows)
    assert _eval(text).legs == ("stub:current liabilities",)


def test_leg_stub_effect_of_dilutive_securities():
    rows = (
        _BALANCE_ROW,
        "Effect of dilutive securities | 900 | 850",
        *_FILLER[:4],
    )
    text = _text("Item | 2024 | 2023", rows)
    assert _eval(text).legs == ("stub:effect of dilutive securities",)


def test_leg_header_purchase():
    rows = (_BALANCE_ROW, *_FILLER)
    assert _eval(_text("Purchase | 2024 | 2023", rows)).legs == ("hdr:purchase",)


def test_plain_equity_statement_is_clear():
    lines = [
        " | December 31, 2024 | December 31, 2023",
        "Balance at December 31, 2023 | 400 | 380",
        "Net income | 90 | 85",
        "Common stock issued | 5 | 4",
        "Dividends declared | 8 | 7",
        "Stock based compensation | 12 | 11",
        "Balance at December 31, 2023 | 499 | 473",
        "Net income | 95 | 90",
        "Balance at December 31, 2024 | 594 | 563",
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
    table = _table((("Common stock", "10"), ("Retained earnings", "50")))
    spec = next(s for s in FORM_TEST_SPECS if s.test_id == "equity_separator")
    verdict = evaluate_form_test_equity_separator(table, spec)
    assert verdict.fired
    assert "core_gate" in verdict.legs


def test_stage_dispatch_stamps_separator_outcome():
    table = _table((("Common stock", "10"), ("Retained earnings", "50")))
    outcomes = {o.test_id: o for o in evaluate_form_tests(table)}
    outcome = outcomes["equity_separator"]
    assert outcome.kind == TEST_EQUITY_SEPARATOR
    assert not outcome.passed and outcome.evaluable
    assert outcome.points == 0.0


# ---------------- competition gate ----------------

_SCORE = {
    "equity_statement": FamilyScore("equity_statement", 11.0, {"signature": 11.0}, ())
}


def _outcome(passed: bool, evaluable: bool = True) -> FormTestOutcome:
    return FormTestOutcome(
        "equity_statement",
        "equity_separator",
        TEST_EQUITY_SEPARATOR,
        passed,
        evaluable,
        0,
        0.0,
        "equity separator fired: core_gate",
    )


def test_gate_removes_claim_on_fired_outcome():
    geometry = GeometryText(form_tests=(_outcome(False),))
    result = compete(geometry, scores=dict(_SCORE))
    assert "equity_statement" not in result.claims
    evidence = result.scores["equity_statement"].evidence
    assert any(
        item.channel == "gate" and "separator fired" in item.detail for item in evidence
    )


def test_gate_keeps_claim_on_clear_outcome():
    geometry = GeometryText(form_tests=(_outcome(True),))
    result = compete(geometry, scores=dict(_SCORE))
    assert "equity_statement" in result.claims


def test_gate_keeps_claim_when_outcome_absent():
    result = compete(GeometryText(), scores=dict(_SCORE))
    assert "equity_statement" in result.claims


def test_gate_keeps_claim_when_outcome_unevaluable():
    geometry = GeometryText(form_tests=(_outcome(False, evaluable=False),))
    result = compete(geometry, scores=dict(_SCORE))
    assert "equity_statement" in result.claims


# ---------------- assignment pass ----------------


def _geometry(stubs, headers=(), grid_rows=20):
    return GeometryText(stubs=stubs, headers=headers, grid_rows=grid_rows)


def _result(*families):
    scores = {
        family: FamilyScore(family, 11.0, {"signature": 11.0}, ())
        for family in families
    }
    return CompetitionResult(claims=families, contested=(), scores=scores)


def test_candidate_score_ranks_core_first():
    strong = equity_candidate_features(
        EquitySeparatorText(
            _text(
                "Item | 2024 | 2023",
                (
                    "Balance at December 31, 2023 | 5 | 6",
                    "Balance at December 31, 2024 | 7 | 8",
                    "Net income | 9 | 9",
                ),
            )
        ),
        SPEC,
    )
    weak = equity_candidate_features(
        EquitySeparatorText(_text("Item | 2024 | 2023", ("Common stock | 1 | 1",))),
        SPEC,
    )
    assert strong.score > weak.score
    assert strong.dated_balance_rows == 2


def test_assignment_eliminates_strictly_dominated():
    strong = _geometry(
        (
            "Balance at December 31, 2023",
            "Balance at December 31, 2024",
            "Net income",
        )
    )
    weak = _geometry(("Common stock", "Retained earnings"))
    results = apply_equity_assignment(
        [strong, weak],
        [_result("equity_statement"), _result("equity_statement")],
    )
    assert "equity_statement" in results[0].claims
    assert "equity_statement" not in results[1].claims
    evidence = results[1].scores["equity_statement"].evidence
    assert any(item.channel == "gate" for item in evidence)


def test_assignment_keeps_tied_candidates():
    geo = _geometry(("Balance at December 31, 2023", "Net income"))
    results = apply_equity_assignment(
        [geo, geo],
        [_result("equity_statement"), _result("equity_statement")],
    )
    assert all("equity_statement" in r.claims for r in results)


def test_assignment_keeps_cross_claimed_geometry():
    geo = _geometry(("Balance at December 31, 2023", "Net income"))
    results = apply_equity_assignment(
        [geo], [_result("equity_statement", "aoci_rollforward")]
    )
    assert "equity_statement" in results[0].claims
    assert "aoci_rollforward" in results[0].claims


def test_assignment_leaves_singleton_and_other_families():
    geo = _geometry(("Common stock",))
    results = apply_equity_assignment(
        [geo, geo],
        [_result("equity_statement"), _result("balance_sheet")],
    )
    assert "equity_statement" in results[0].claims
    assert "balance_sheet" in results[1].claims
