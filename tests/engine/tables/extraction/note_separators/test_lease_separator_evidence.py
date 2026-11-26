"""Lease separator (TEST_LEASE_SEPARATOR): legs, gate, assignment."""

from __future__ import annotations

import edgar_sec.engine.tables.extraction.note_separators.lease_separator_evidence as _lse
from edgar_sec.engine.tables.ascii_html.model.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.cascade.competition import compete
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
    geometry_text_from_table,
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
    PROV_LEASE_SEPARATOR,
    TEST_ADMISSION_EVIDENCE,
    TEST_LADDER,
    TEST_LEASE_SEPARATOR,
)
from edgar_sec.engine.tables.extraction.core.subjects.profiles import (
    profile_for,
)
from edgar_sec.engine.tables.extraction.note_separators.lease_separator_evidence import (
    LeaseSeparatorText,
    apply_lease_assignment,
    evaluate_form_test_lease_separator,
    evaluate_lease_separator,
)
from edgar_sec.engine.tables.extraction.note_separators.lease_separator_specs import (
    LEASE_SEPARATOR_SPECS,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import structure_table
from edgar_sec.foundation.text.date_patterns import (
    YEAR_TOKEN_SEARCH_RE as _HOME_YEAR_RE,
)

SPEC = LEASE_SEPARATOR_SPECS["lease_maturity"]
FAMILY = "lease_maturity"
ANCHOR = "debt_maturity"


def _eval(table_text: str):
    return evaluate_lease_separator(LeaseSeparatorText(table_text), SPEC)


def test_kind_is_declared_as_form_test_data():
    entry = next(
        s
        for s in FORM_TEST_SPECS
        if s.family == FAMILY and s.kind == TEST_LEASE_SEPARATOR
    )
    assert entry.test_id == "lease_separator"
    assert entry.points == 0.0
    assert entry.provenance == PROV_LEASE_SEPARATOR
    assert SPEC.family == FAMILY
    assert TEST_LEASE_SEPARATOR in profile_for(FAMILY).form_tests


def test_spec_carries_the_priced_legs():
    legs = [(leg.leg_id, leg.kind, leg.scope) for leg in SPEC.legs]
    assert legs == [
        ("spanprod_le_2", "span", "claim-local"),
        ("assign_sibling_seat", "assign_sibling", "set-level"),
        ("subj_before400", "subject", "claim-local"),
    ]
    anchor = next(leg for leg in SPEC.legs if leg.kind == "assign_sibling")
    assert anchor.anchor_family == ANCHOR
    span = next(leg for leg in SPEC.legs if leg.kind == "span")
    assert span.limit == 2
    subject = next(leg for leg in SPEC.legs if leg.kind == "subject")
    assert subject.pattern == "financing (liability|obligation)"
    assert subject.tail == 400


def test_packet_and_rows_surfaces_agree():
    rows = (
        ("Lease payments", "2026", "2027"),
        ("Rent", "100", "200"),
    )
    caption = ("Lease payments due",)
    prose = "Payments are due monthly."
    via_rows = evaluate_lease_separator(
        LeaseSeparatorText.from_rows(rows, caption, prose), SPEC
    )
    via_packet = evaluate_lease_separator(
        LeaseSeparatorText.from_packet(
            {
                "table_text": "Lease payments | 2026 | 2027\nRent | 100 | 200",
                "caption_stack": ["Lease payments due"],
                "prose_before": "Payments are due monthly.",
            }
        ),
        SPEC,
    )
    assert via_rows == via_packet
    assert via_rows.fired


def test_recognizer_homes():
    assert _lse.YEAR_TOKEN_SEARCH_RE is _HOME_YEAR_RE
    assert _lse.fired_separator_outcome is _CORE_FORM_OUTCOME


# ---------------- the claim-local leg ----------------


def test_leg_spanprod_fires_at_two_years():
    verdict = _eval("Lease payments | 2026 | 2027\nRent | 100 | 200")
    assert verdict.fired
    assert verdict.legs == ("spanprod_le_2",)


def test_leg_spanprod_fires_with_no_years():
    verdict = _eval("Lease payments | Amount\nRent | 100")
    assert verdict.fired
    assert verdict.legs == ("spanprod_le_2",)


def test_leg_spanprod_clear_at_three_years():
    verdict = _eval("Lease payments | 2026 | 2027 | 2028\nRent | 100 | 200 | 300")
    assert not verdict.fired
    assert verdict.legs == ()


def test_leg_spanprod_reads_stub_years():
    text = "Payments | Amount\n2026 rent | 1\n2027 rent | 2\n2028 rent | 3"
    verdict = _eval(text)
    assert not verdict.fired


def test_leg_spanprod_ignores_data_cell_years():
    text = (
        "Payments | Amount | Note\nRent | 2026 | x\nTaxes | 2027 | y\nOther | 2028 | z"
    )
    verdict = _eval(text)
    assert verdict.fired


def test_leg_spanprod_counts_distinct_years_only():
    text = "Payments | 2026 | 2026\nRent in 2026 | 1 | 2\nRent in 2027 | 3 | 4"
    verdict = _eval(text)
    assert verdict.fired


def test_empty_grid_is_unevaluable():
    verdict = _eval("")
    assert not verdict.fired
    assert not verdict.evaluable


# ---------------- the subject leg ----------------

_GRID3 = "Lease payments | 2026 | 2027 | 2028\nRent | 100 | 200 | 300"


def test_leg_subject_fires_on_caption():
    text = LeaseSeparatorText(_GRID3, caption_stack=("Financing liability payments",))
    verdict = evaluate_lease_separator(text, SPEC)
    assert verdict.fired
    assert verdict.legs == ("subj_before400",)


def test_leg_subject_fires_on_prose_tail():
    prose = "x " * 300 + "the financing obligation is due"
    verdict = evaluate_lease_separator(
        LeaseSeparatorText(_GRID3, prose_before=prose), SPEC
    )
    assert verdict.fired
    assert verdict.legs == ("subj_before400",)


def test_leg_subject_ignores_prose_beyond_tail():
    prose = "the financing obligation is due " + "x " * 300
    verdict = evaluate_lease_separator(
        LeaseSeparatorText(_GRID3, prose_before=prose), SPEC
    )
    assert not verdict.fired


def test_leg_subject_ignores_prose_after():
    packet = {
        "table_text": _GRID3,
        "caption_stack": ["Lease payments"],
        "prose_before": "Payments are due monthly.",
        "prose_after": "Financing liability payments are shown below.",
    }
    verdict = evaluate_lease_separator(LeaseSeparatorText.from_packet(packet), SPEC)
    assert not verdict.fired


# ---------------- stage adapter + dispatch ----------------


def _table(rows, caption_stack=(), prose_before=""):
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


def test_stage_adapter_over_full_grid():
    table = _table((("Lease payments", "2026", "2027"),))
    spec = next(s for s in FORM_TEST_SPECS if s.test_id == "lease_separator")
    verdict = evaluate_form_test_lease_separator(table, spec)
    assert verdict.fired
    assert "spanprod_le_2" in verdict.legs


def test_stage_adapter_reads_context_subject_surface():
    table = _table(
        (("Lease payments", "2026", "2027", "2028"),),
        caption_stack=("Financing liability payments",),
    )
    spec = next(s for s in FORM_TEST_SPECS if s.test_id == "lease_separator")
    verdict = evaluate_form_test_lease_separator(table, spec)
    assert verdict.fired
    assert verdict.legs == ("subj_before400",)


def test_stage_dispatch_stamps_separator_outcome():
    table = _table((("Lease payments", "2026", "2027"),))
    outcomes = {o.test_id: o for o in evaluate_form_tests(table)}
    outcome = outcomes["lease_separator"]
    assert outcome.kind == TEST_LEASE_SEPARATOR
    assert not outcome.passed and outcome.evaluable
    assert outcome.points == 0.0


# ---------------- competition gate ----------------

_SCORE = {FAMILY: FamilyScore(FAMILY, 11.0, {"signature": 11.0}, ())}


def _outcome(passed: bool, evaluable: bool = True) -> FormTestOutcome:
    return FormTestOutcome(
        FAMILY,
        "lease_separator",
        TEST_LEASE_SEPARATOR,
        passed,
        evaluable,
        0,
        0.0,
        "separator fired: spanprod_le_2",
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


def _debt_outcome(test_id, kind, passed):
    return FormTestOutcome(ANCHOR, test_id, kind, passed, True, 0, 0.0, "")


_SEATED = (
    _debt_outcome("debt_maturity_year_ladder", TEST_LADDER, True),
    _debt_outcome("debt_maturity_j1_admission", TEST_ADMISSION_EVIDENCE, True),
)
_LADDER_ONLY = (
    _debt_outcome("debt_maturity_year_ladder", TEST_LADDER, True),
    _debt_outcome("debt_maturity_j1_admission", TEST_ADMISSION_EVIDENCE, False),
)


def test_assignment_refuses_when_debt_seat_seated():
    results = apply_lease_assignment(
        [GeometryText(form_tests=_SEATED)],
        [_result_scored((FAMILY,), {FAMILY: 11.0, ANCHOR: 20.0})],
    )
    assert FAMILY not in results[0].claims
    evidence = results[0].scores[FAMILY].evidence
    assert any(
        item.detail == "lease assignment: geometry seated to debt_maturity"
        for item in evidence
    )


def test_assignment_refuses_when_geometry_co_claimed():
    results = apply_lease_assignment(
        [GeometryText()],
        [_result(FAMILY, "balance_sheet")],
    )
    assert FAMILY not in results[0].claims
    assert "balance_sheet" in results[0].claims
    evidence = results[0].scores[FAMILY].evidence
    assert any(
        item.detail == "lease assignment: geometry co-claimed" for item in evidence
    )


def test_assignment_co_claim_note_takes_precedence_over_debt_seat():
    results = apply_lease_assignment(
        [GeometryText(form_tests=_SEATED)],
        [_result(FAMILY, ANCHOR)],
    )
    assert FAMILY not in results[0].claims
    assert ANCHOR in results[0].claims
    evidence = results[0].scores[FAMILY].evidence
    assert any(
        item.detail == "lease assignment: geometry co-claimed" for item in evidence
    )
    assert not any("seated to debt_maturity" in item.detail for item in evidence)


def test_assignment_keeps_unopposed_solo_claim():
    results = apply_lease_assignment(
        [GeometryText()],
        [_result(FAMILY)],
    )
    assert FAMILY in results[0].claims


def test_assignment_keeps_claim_when_admission_fails():
    results = apply_lease_assignment(
        [GeometryText(form_tests=_LADDER_ONLY)],
        [_result(FAMILY)],
    )
    assert FAMILY in results[0].claims


def test_assignment_keeps_claim_when_outcomes_absent():
    results = apply_lease_assignment(
        [GeometryText()],
        [_result(FAMILY)],
    )
    assert FAMILY in results[0].claims


def test_assignment_keeps_claim_without_lease_claim():
    results = apply_lease_assignment(
        [GeometryText(form_tests=_SEATED)],
        [_result(ANCHOR)],
    )
    assert ANCHOR in results[0].claims


def test_assignment_preserves_cross_claims():
    results = apply_lease_assignment(
        [GeometryText(form_tests=_SEATED)],
        [_result(FAMILY, ANCHOR, "balance_sheet")],
    )
    assert FAMILY not in results[0].claims
    assert ANCHOR in results[0].claims
    assert "balance_sheet" in results[0].claims


def test_assignment_leaves_other_families_alone():
    results = apply_lease_assignment(
        [GeometryText(form_tests=_SEATED), GeometryText(form_tests=_SEATED)],
        [_result(ANCHOR), _result("balance_sheet")],
    )
    assert ANCHOR in results[0].claims
    assert "balance_sheet" in results[1].claims


def test_year_span_prod_counts_the_full_range():
    text = LeaseSeparatorText("2024 | 5\n2025 | 5\n2100 | 5")
    assert _lse.year_span_prod(text) == 3


def test_stub_ladder_purity_full_ladder():
    text = LeaseSeparatorText(
        "Payments | Amount\n2026 | 1\n2027 | 2\nThereafter | 3\nTotal | 6"
    )
    assert _lse.stub_ladder_purity(text) == 1.0


def test_stub_ladder_purity_mixed_stub():
    text = LeaseSeparatorText("Payments | Amount\n2026 | 1\nRent expense | 2")
    assert _lse.stub_ladder_purity(text) == 0.5


def test_stub_ladder_purity_none_without_stub_cells():
    assert _lse.stub_ladder_purity(LeaseSeparatorText("Payments | Amount")) is None
    assert _lse.stub_ladder_purity(LeaseSeparatorText("")) is None


def test_geometry_text_carries_span_and_purity():
    table = _table(
        (
            ("Payments", "Amount"),
            ("2026", "1"),
            ("2027", "2"),
            ("2028", "3"),
            ("Thereafter", "4"),
            ("Total", "10"),
        )
    )
    geometry = geometry_text_from_table(table, evaluate_stage=False)
    assert geometry.year_span == 3
    assert geometry.stub_ladder_purity == 1.0


def test_period_stub_bare_year_and_bands():
    assert _lse.period_stub_present(LeaseSeparatorText("P | A\n2026 | 1"))
    assert _lse.period_stub_present(LeaseSeparatorText("P | A\nWithin one year | 1"))
    assert _lse.period_stub_present(LeaseSeparatorText("P | A\nYear 1 | 1"))
    assert _lse.period_stub_present(LeaseSeparatorText("P | A\nThereafter | 1"))


def test_period_stub_instrument_vintage_is_not_a_period():
    text = LeaseSeparatorText("P | A\n2019 Credit Agreement | 219.9")
    assert not _lse.period_stub_present(text)


def test_transposed_axis_needs_period_columns_and_lease_stubs():
    transposed = LeaseSeparatorText(
        " | Total | 2020 | 2021 | 2022 | Thereafter\n"
        "Capital lease obligations | 41 | 13 | 10 | 7 | 0"
    )
    assert _lse.transposed_period_axis(transposed)
    balances = LeaseSeparatorText(
        "(in millions) | 2019 | 2018\n2019 Credit Agreement | 219.9 | —"
    )
    assert not _lse.transposed_period_axis(balances)


def test_column_mass_shares_combined_grid():
    text = LeaseSeparatorText(
        " | Finance Leases | Debt | Total\n"
        "2023 | 1.6 | 50.4 | 52.0\n2024 | 0.4 | 260.9 | 261.3"
    )
    shares = _lse.column_mass_shares(text)
    assert shares is not None
    lease_share, foreign_share = shares
    assert lease_share < 0.01
    assert foreign_share > 0.5


def test_column_mass_shares_none_for_period_columns():
    text = LeaseSeparatorText(" | 2023 | 2024\nOperating | 1 | 2")
    assert _lse.column_mass_shares(text) is None


def test_stub_refusal_reason_clauses():
    assert _lse.stub_refusal_reason(False, False, None) is not None
    assert _lse.stub_refusal_reason(None, None, None) is None
    assert _lse.stub_refusal_reason(None, False, None) is None
    assert _lse.stub_refusal_reason(False, True, None) is None
    assert _lse.stub_refusal_reason(True, False, None) is None
    assert _lse.stub_refusal_reason(True, False, (0.001, 0.9)) is not None
    assert _lse.stub_refusal_reason(True, False, (0.4, 0.6)) is None


def test_apply_lease_stub_refusal_removes_only_refused_claims():
    claimed = CompetitionResult(
        claims=(FAMILY,),
        contested=(),
        scores={FAMILY: FamilyScore(FAMILY, 9.0, {"signature": 9.0}, ())},
        groups=(),
    )
    bare = GeometryText(period_stub_present=False, transposed_period_axis=False)
    (out,) = _lse.apply_lease_stub_refusal([bare], [claimed])
    assert out.claims == ()
    assert out.scores[FAMILY].evidence[-1].channel == "gate"
    period = GeometryText(period_stub_present=True)
    (kept,) = _lse.apply_lease_stub_refusal([period], [claimed])
    assert kept.claims == (FAMILY,)
    unread = GeometryText()
    (untouched,) = _lse.apply_lease_stub_refusal([unread], [claimed])
    assert untouched.claims == (FAMILY,)


def test_transposed_axis_comparative_years_do_not_qualify():
    expense = LeaseSeparatorText(
        " | 2025 | 2024 | 2023\n"
        "Operating lease expense | 7,734 | 8,245 | 7,685\n"
        "Total lease expense | 10,413 | 11,697 | 10,757"
    )
    assert not _lse.transposed_period_axis(expense)


def test_period_step_count_reads():
    bands = LeaseSeparatorText(
        " | Operating\nWithin one year | 7.2\nOne to two years | 5.7\n"
        "Thereafter | 25.6\nTotal lease payments | 52.2"
    )
    assert _lse.period_step_count(bands) == 3
    partial = LeaseSeparatorText(
        "H | A\n2024 | 16,250\n2025 | 16,670\nJuly & August 2025 | 2,790\n"
        "Total future minimum lease payments | 35,710"
    )
    assert _lse.period_step_count(partial) == 3
    plain = LeaseSeparatorText("H | A\nCost of revenue | 1\nTotal | 2")
    assert _lse.period_step_count(plain) == 0


def test_period_purity_reads():
    bands = LeaseSeparatorText(
        " | Operating\nWithin one year | 7.2\nOne to two years | 5.7\n"
        "Thereafter | 25.6\nTotal lease payments | 52.2"
    )
    assert _lse.period_purity(bands) == 1.0
    years = LeaseSeparatorText("H | A\n2026 | 1\nTotal | 2\nLess: interest | 3")
    assert _lse.period_purity(years) == 2 / 3
    plain = LeaseSeparatorText("H | A\nCost of revenue | 1\nTotal | 2")
    assert _lse.period_purity(plain) == 0.5


def _result_scored(claims, totals):
    scores = {
        family: FamilyScore(family, total, {"signature": total}, ())
        for family, total in totals.items()
    }
    return CompetitionResult(claims=claims, contested=(), scores=scores)


def test_assignment_refuses_when_debt_seat_seated_and_debt_dominates():
    results = apply_lease_assignment(
        [GeometryText(form_tests=_SEATED)],
        [_result_scored((FAMILY,), {FAMILY: 11.0, ANCHOR: 20.0})],
    )
    assert FAMILY not in results[0].claims


def test_assignment_keeps_claim_when_lease_dominates_the_debt_seat():
    results = apply_lease_assignment(
        [GeometryText(form_tests=_SEATED)],
        [_result_scored((FAMILY,), {FAMILY: 58.5, ANCHOR: 1.5})],
    )
    assert FAMILY in results[0].claims


def test_block_purity_reads():
    tailed = LeaseSeparatorText(
        "H | A\n2023 | 1\n2024 | 2\nThereafter | 3\n"
        "Total undiscounted lease payments | 6\nLess: imputed interest | 1\n"
        "Total lease liabilities | 5"
    )
    assert _lse.block_purity(tailed) == 1.0
    stacked = LeaseSeparatorText(
        "H | A\n2023 | 1\n2024 | 2\nTotal - operating | 3\n"
        "Financing leases: | \n2023 | 4\nTotal - finance | 5"
    )
    assert _lse.block_purity(stacked) == 4 / 5
    plain = LeaseSeparatorText("H | A\nCost of revenue | 1\nTotal | 2")
    assert _lse.block_purity(plain) is None
