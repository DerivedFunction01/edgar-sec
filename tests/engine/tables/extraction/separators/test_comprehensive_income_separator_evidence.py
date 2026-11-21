"""Comprehensive-income separator (TEST_COMPREHENSIVE_INCOME_SEPARATOR)."""

from __future__ import annotations

import edgar_sec.engine.tables.extraction.separators.comprehensive_income_separator_evidence as _cise
from edgar_sec.engine.tables.ascii_html.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.cascade.competition import compete
from edgar_sec.engine.tables.extraction.cascade.geometry_text import GeometryText
from edgar_sec.engine.tables.extraction.separators.comprehensive_income_separator_evidence import (
    ComprehensiveIncomeSeparatorText,
    apply_comprehensive_income_assignment,
    comprehensive_income_candidate_features,
    evaluate_comprehensive_income_separator,
    evaluate_form_test_comprehensive_income_separator,
)
from edgar_sec.engine.tables.extraction.separators.comprehensive_income_separator_specs import (
    COMPREHENSIVE_INCOME_SEPARATOR_SPECS,
)
from edgar_sec.engine.tables.extraction.core.context import TableContext
from edgar_sec.engine.tables.extraction.form_specs.form_test_specs import (
    FORM_TEST_SPECS,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_types import (
    FormTestOutcome,
)
from edgar_sec.engine.tables.extraction.form_tests.form_tests import evaluate_form_tests
from edgar_sec.engine.tables.extraction.cascade.geometry_scoring import (
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
from edgar_sec.engine.tables.extraction.core.profiles import (
    PROV_COREFIN_COMPINCOME,
    TEST_COMPREHENSIVE_INCOME_SEPARATOR,
    profile_for,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import structure_table

SPEC = COMPREHENSIVE_INCOME_SEPARATOR_SPECS["comprehensive_income"]

_CORE_ROWS = (
    "Net income | 100 | 95",
    "Other comprehensive income | 5 | 4",
    "Comprehensive income | 105 | 99",
)


def _eval(table_text: str):
    return evaluate_comprehensive_income_separator(
        ComprehensiveIncomeSeparatorText(table_text), SPEC
    )


def _text(header: str, rows: tuple[str, ...]) -> str:
    return "\n".join([header, *rows])


def test_kind_is_declared_as_form_test_data():
    entry = next(
        s
        for s in FORM_TEST_SPECS
        if s.family == "comprehensive_income"
        and s.kind == TEST_COMPREHENSIVE_INCOME_SEPARATOR
    )
    assert entry.test_id == "comprehensive_income_separator"
    assert entry.points == 0.0
    assert entry.provenance == PROV_COREFIN_COMPINCOME
    assert SPEC.family == "comprehensive_income"
    assert (
        TEST_COMPREHENSIVE_INCOME_SEPARATOR
        in profile_for("comprehensive_income").form_tests
    )


def test_packet_and_rows_surfaces_agree():
    rows = (("Net income", "100"), ("Comprehensive income", "105"))
    via_rows = evaluate_comprehensive_income_separator(
        ComprehensiveIncomeSeparatorText.from_rows(rows), SPEC
    )
    via_packet = evaluate_comprehensive_income_separator(
        ComprehensiveIncomeSeparatorText.from_packet(
            {"table_text": "Net income | 100\nComprehensive income | 105"}
        ),
        SPEC,
    )
    assert via_rows == via_packet


def test_recognizer_homes():
    assert _cise.stub_key is _PENSION_STUB_KEY
    assert _cise.header_keys is _PENSION_HEADER_KEYS
    assert _cise.HEADER_STOP_TOKENS is _PENSION_STOP_TOKENS
    assert _cise._YEAR_RE.pattern == r"\b(?:19|20)\d{2}\b"


# ---------------- the claim-local legs ----------------


def test_leg_rows_gt_21():
    rows = (
        "Net income | 100 | 95",
        "Other comprehensive income | 5 | 4",
        *(["Unrealized gain on securities | 1 | 1"] * 20),
    )
    assert _eval(_text(" | 2024 | 2023", rows)).legs == ("rows_gt_21",)


def test_leg_span_ge_4():
    text = _text(" | 2024 | 2023 | 2022 | 2021", _CORE_ROWS)
    assert _eval(text).legs == ("span_ge_4",)


def test_leg_core_incomplete():
    text = _text(" | 2024 | 2023", ("Common stock | 10", "Cash | 5"))
    assert _eval(text).legs == ("core_incomplete",)


def test_leg_hdr_accumulated():
    text = _text("Accumulated other comprehensive income | 2024 | 2023", _CORE_ROWS)
    assert _eval(text).legs == ("hdr_accumulated",)


def test_leg_bookend_and_accum():
    rows = (
        *_CORE_ROWS,
        "Balance at beginning of period | 40 | 38",
        "Balance at end of period | 45 | 40",
    )
    text = _text("Accumulated other comprehensive income | 2024 | 2023", rows)
    assert _eval(text).legs == ("hdr_accumulated", "bookend_and_accum")


def test_leg_descent():
    rows = (*_CORE_ROWS, "Gross profit | 50 | 45")
    assert _eval(_text(" | 2024 | 2023", rows)).legs == ("descent",)


def test_leg_host_equity():
    rows = (*_CORE_ROWS, "Common stock | 10 | 10", "Retained earnings | 60 | 55")
    assert _eval(_text(" | 2024 | 2023", rows)).legs == ("host_equity",)


def test_leg_detail_taxcol():
    text = _text("Income tax benefit (pretax) | 2024 | 2023", _CORE_ROWS)
    assert _eval(text).legs == ("detail_taxcol",)


def test_leg_guarantor():
    rows = (*_CORE_ROWS, "Guarantor subsidiaries | 5 | 5")
    assert _eval(_text(" | 2024 | 2023", rows)).legs == ("guarantor",)


def test_plain_comprehensive_income_statement_is_clear():
    lines = [
        " | 2024 | 2023",
        "Net income | 100 | 95",
        "Foreign currency translation adjustment | 2 | 1",
        "Unrealized gain on available for sale securities | 3 | 2",
        "Pension liability adjustment | 1 | 1",
        "Other comprehensive income | 6 | 4",
        "Comprehensive income | 106 | 99",
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
    table = _table((("Common stock", "10"), ("Cash", "5")))
    spec = next(
        s for s in FORM_TEST_SPECS if s.test_id == "comprehensive_income_separator"
    )
    verdict = evaluate_form_test_comprehensive_income_separator(table, spec)
    assert verdict.fired
    assert "core_incomplete" in verdict.legs


def test_stage_dispatch_stamps_separator_outcome():
    table = _table((("Common stock", "10"), ("Cash", "5")))
    outcomes = {o.test_id: o for o in evaluate_form_tests(table)}
    outcome = outcomes["comprehensive_income_separator"]
    assert outcome.kind == TEST_COMPREHENSIVE_INCOME_SEPARATOR
    assert not outcome.passed and outcome.evaluable
    assert outcome.points == 0.0


# ---------------- competition gate ----------------

_SCORE = {
    "comprehensive_income": FamilyScore(
        "comprehensive_income", 11.0, {"signature": 11.0}, ()
    )
}


def _outcome(passed: bool, evaluable: bool = True) -> FormTestOutcome:
    return FormTestOutcome(
        "comprehensive_income",
        "comprehensive_income_separator",
        TEST_COMPREHENSIVE_INCOME_SEPARATOR,
        passed,
        evaluable,
        0,
        0.0,
        "comprehensive income separator fired: core_incomplete",
    )


def test_gate_removes_claim_on_fired_outcome():
    geometry = GeometryText(form_tests=(_outcome(False),))
    result = compete(geometry, scores=dict(_SCORE))
    assert "comprehensive_income" not in result.claims
    evidence = result.scores["comprehensive_income"].evidence
    assert any(
        item.channel == "gate" and "separator fired" in item.detail for item in evidence
    )


def test_gate_keeps_claim_on_clear_outcome():
    geometry = GeometryText(form_tests=(_outcome(True),))
    result = compete(geometry, scores=dict(_SCORE))
    assert "comprehensive_income" in result.claims


def test_gate_keeps_claim_when_outcome_absent():
    result = compete(GeometryText(), scores=dict(_SCORE))
    assert "comprehensive_income" in result.claims


def test_gate_keeps_claim_when_outcome_unevaluable():
    geometry = GeometryText(form_tests=(_outcome(False, evaluable=False),))
    result = compete(geometry, scores=dict(_SCORE))
    assert "comprehensive_income" in result.claims


# ---------------- assignment pass ----------------


def _geometry(stubs):
    return GeometryText(stubs=stubs)


def _result(*families):
    scores = {
        family: FamilyScore(family, 11.0, {"signature": 11.0}, ())
        for family in families
    }
    return CompetitionResult(claims=families, contested=(), scores=scores)


def test_candidate_features_read_the_core():
    strong = comprehensive_income_candidate_features(
        ComprehensiveIncomeSeparatorText(_text(" | 2024 | 2023", _CORE_ROWS)),
        SPEC,
    )
    weak = comprehensive_income_candidate_features(
        ComprehensiveIncomeSeparatorText(
            _text(" | 2024 | 2023", ("Common stock | 1 | 1",))
        ),
        SPEC,
    )
    assert strong.core_complete
    assert not weak.core_complete


def test_assignment_eliminates_core_incomplete_below_complete_sibling():
    strong = _geometry(
        ("Net income", "Other comprehensive income", "Comprehensive income")
    )
    weak = _geometry(("Common stock", "Retained earnings"))
    results = apply_comprehensive_income_assignment(
        [strong, weak],
        [_result("comprehensive_income"), _result("comprehensive_income")],
    )
    assert "comprehensive_income" in results[0].claims
    assert "comprehensive_income" not in results[1].claims
    evidence = results[1].scores["comprehensive_income"].evidence
    assert any(item.channel == "gate" for item in evidence)


def test_assignment_keeps_all_complete_candidates():
    geo = _geometry(
        ("Net income", "Other comprehensive income", "Comprehensive income")
    )
    results = apply_comprehensive_income_assignment(
        [geo, geo],
        [_result("comprehensive_income"), _result("comprehensive_income")],
    )
    assert all("comprehensive_income" in r.claims for r in results)


def test_assignment_keeps_all_incomplete_candidates():
    geo = _geometry(("Common stock", "Retained earnings"))
    results = apply_comprehensive_income_assignment(
        [geo, geo],
        [_result("comprehensive_income"), _result("comprehensive_income")],
    )
    assert all("comprehensive_income" in r.claims for r in results)


def test_assignment_leaves_singleton_and_other_families():
    geo = _geometry(("Common stock",))
    results = apply_comprehensive_income_assignment(
        [geo, geo],
        [_result("comprehensive_income"), _result("balance_sheet")],
    )
    assert "comprehensive_income" in results[0].claims
    assert "balance_sheet" in results[1].claims
