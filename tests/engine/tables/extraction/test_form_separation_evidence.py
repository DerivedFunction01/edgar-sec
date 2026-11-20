"""Form separation (TEST_FORM_SEPARATION): declaration, dispatch, gate."""

from __future__ import annotations

import edgar_sec.engine.tables.extraction.form_separation_evidence as _fse
from edgar_sec.engine.tables.ascii_html.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.competition import (
    GeometryText,
    compete,
)
from edgar_sec.engine.tables.extraction.context import TableContext
from edgar_sec.engine.tables.extraction.form_separation_evidence import (
    FormSeparationText,
    evaluate_form_separation,
)
from edgar_sec.engine.tables.extraction.form_separation_specs import (
    FORM_SEPARATION_SPECS,
)
from edgar_sec.engine.tables.extraction.form_test_specs import FORM_TEST_SPECS
from edgar_sec.engine.tables.extraction.form_tests import (
    FormTestOutcome,
    evaluate_form_tests,
)
from edgar_sec.engine.tables.extraction.geometry_scoring import FamilyScore
from edgar_sec.engine.tables.extraction.pension_routed_evidence import (
    header_keys as _PENSION_HEADER_KEYS,
    stub_key as _PENSION_STUB_KEY,
)
from edgar_sec.engine.tables.extraction.profiles import (
    PROV_CASCADE_G4_FORM_SEPARATION,
    PROV_RELATED_PARTY_FORM_SEPARATION,
    TEST_FORM_SEPARATION,
    profile_for,
)
from edgar_sec.engine.tables.extraction.typed_rows import structure_table

SPEC = FORM_SEPARATION_SPECS["related_party"]
EPS_SPEC = FORM_SEPARATION_SPECS["eps_reconciliation"]
INT_SPEC = FORM_SEPARATION_SPECS["intangibles"]


def _eval(table_text: str, caption_stack=()):
    return evaluate_form_separation(FormSeparationText(table_text, caption_stack), SPEC)


def _eval_eps(table_text: str, caption_stack=()):
    return evaluate_form_separation(
        FormSeparationText(table_text, caption_stack), EPS_SPEC
    )


def _eval_int(table_text: str, caption_stack=()):
    return evaluate_form_separation(
        FormSeparationText(table_text, caption_stack), INT_SPEC
    )


def test_kind_is_declared_as_form_test_data():
    entry = next(
        s
        for s in FORM_TEST_SPECS
        if s.family == "related_party" and s.kind == TEST_FORM_SEPARATION
    )
    assert entry.test_id == "related_party_form_separation"
    assert entry.points == 0.0
    assert entry.provenance == PROV_RELATED_PARTY_FORM_SEPARATION
    assert SPEC.family == "related_party"
    assert TEST_FORM_SEPARATION in profile_for("related_party").form_tests


def test_eps_and_intangibles_are_declared_as_form_test_data():
    for family, test_id in (
        ("eps_reconciliation", "eps_reconciliation_form_separation"),
        ("intangibles", "intangibles_form_separation"),
    ):
        entry = next(
            s
            for s in FORM_TEST_SPECS
            if s.family == family and s.kind == TEST_FORM_SEPARATION
        )
        assert entry.test_id == test_id
        assert entry.points == 0.0
        assert entry.provenance == PROV_CASCADE_G4_FORM_SEPARATION
        assert TEST_FORM_SEPARATION in profile_for(family).form_tests


def test_packet_and_rows_surfaces_agree():
    rows = (
        ("Due from related parties", "10"),
        ("Due to related parties", "50"),
    )
    via_rows = evaluate_form_separation(FormSeparationText.from_rows(rows), SPEC)
    via_packet = evaluate_form_separation(
        FormSeparationText.from_packet(
            {
                "table_text": (
                    "Due from related parties | 10\nDue to related parties | 50"
                )
            }
        ),
        SPEC,
    )
    assert via_rows == via_packet


def test_recognizer_homes():
    assert _fse.stub_key is _PENSION_STUB_KEY
    assert _fse.header_keys is _PENSION_HEADER_KEYS


def test_empty_grid_is_unevaluable():
    verdict = _eval("")
    assert not verdict.fired
    assert not verdict.evaluable


# ---------------- the priced class legs ----------------


def test_leg_furniture_signature_block():
    text = (
        "/s/ Liggett & Webb, P.A.\n"
        "We have served as the Company's auditor since 2021.\n"
        "Boynton Beach, Florida\n"
        "June 28, 2022"
    )
    assert _eval(text).legs == ("form:furniture",)


def test_leg_gold_eps_reconciliation():
    text = (
        " | 2020 | 2019\n"
        "Numerator: |  | \n"
        "Net loss attributable to the company | $ | (55,998)\n"
        "Denominator: |  | \n"
        "Weighted average shares outstanding, basic and diluted | 160,338\n"
        "Net loss per share, basic and diluted | $ | (0.35)"
    )
    assert _eval(text).legs == ("form:gold:eps_reconciliation",)


def test_leg_supplemental_schedule_audit_fees():
    text = (
        " | 2017 | 2016\n"
        "Audit Fees (1) | $ | 12,000\n"
        "Audit Related Fees (2) | $ | 0\n"
        "Tax Fees (3) | $ | 0\n"
        "All Other Fees | $ | 0"
    )
    assert _eval(text).legs == ("form:supplemental-schedule",)


def test_leg_supplemental_schedule_firm_rows():
    text = "2012 | $ | 14,000 | M&K CPAS, PLLC\n2011 | $ | 10,000 | M&K CPAS, PLLC"
    assert _eval(text).legs == ("form:supplemental-schedule",)


def test_leg_gold_lease_maturity():
    text = (
        "2017 | $ | 6,576\n"
        "2018 |  | 5,173\n"
        "2019 |  | 4,052\n"
        "2020 |  | 3,038\n"
        "Thereafter |  | 338"
    )
    assert _eval(text).legs == ("form:gold:lease_maturity",)


def test_leg_statement_summary():
    text = (
        " | 2019 | 2018\n"
        "Total Revenues from Continuing Operations | $ | 2,093,018\n"
        "Operating Expenses from Continuing Operations |  | (2,242,760)\n"
        "Interest Income from Continuing Operations |  | 2,814\n"
        "Consolidated Net (Loss) Income from Continuing Operations"
        " |  | (269,830)"
    )
    assert _eval(text).legs == ("form:statement-summary",)


def test_leg_percentage_rows():
    text = (
        " | December 31, 2021 |  | December 31, 2020 | \n"
        "Midwest |  | 17.0 | % |  | 18.2 | %\n"
        "South |  | 38.2 |  |  | 42.3 | \n"
        "Total |  | 100.0 | % |  | 100.0 | %"
    )
    assert _eval(text).legs == ("form:percentage-rows",)


def test_leg_segment_detail():
    text = (
        " | June 29, 2025 | June 30, 2024 | $ Change | % Change\n"
        "Residential Solar Installation | $ | 37,396 | $ | 32,904\n"
        "New Homes Business |  | 30,128 |  | 30,128\n"
        "Total revenue | $ | 67,524 | $ | 63,032"
    )
    assert _eval(text).legs == ("form:segment-detail",)


def test_leg_composition():
    text = (
        " | 2007 | 2006\n"
        "Nonaccrual Loans | $ | 1,939\n"
        "Loans Past Due 90 or More Days and Still Accruing Interest |  | 245\n"
        "Total Nonperforming Loans | $ | 2,184"
    )
    assert _eval(text).legs == ("form:composition",)


def test_leg_gold_warrant_activity():
    text = (
        "Common shares purchasable upon exercise of warrants |  |  | \n"
        "Weighted average exercise price |  |  | \n"
        "Weighted average remaining contractual life |  |  | \n"
        "Aggregate intrinsic value |  |  | \n"
        "Balance, December 31, 2012 |  | 1,000\n"
        "Balance, December 31, 2013 |  | 900\n"
        "Balance, December 31, 2014 |  | 800\n"
        "Exercised |  | (100)"
    )
    assert _eval_eps(text).legs == ("form:gold:warrant_activity",)


def test_warrant_stubs_without_exercise_price_are_not_warrant_activity():
    text = (
        " | 2020 | 2019\n"
        "Numerator: |  | \n"
        "Net loss attributable to the company | $ | (55,998)\n"
        "Denominator: |  | \n"
        "Weighted average shares outstanding, basic and diluted | 160,338\n"
        "Warrants |  | 5,000\n"
        "Net loss per share, basic and diluted | $ | (0.35)"
    )
    assert not _eval_eps(text).fired


def test_leg_gold_debt_maturity():
    text = (
        " | 2010 | 2011 | 2012 | 2013 | 2014 | Thereafter | Total | FV\n"
        "Long term debt | $ | 100 | 100 | 100 | 100 | 100 | 100 | 600 | 590\n"
        "Fixed rate |  | 5.0 | 5.0 | 5.0 | 5.0 | 5.0 | 5.0 |  | \n"
        "Average interest rate |  | 5.0 | 5.0 | 5.0 | 5.0 | 5.0 | 5.0 |  | \n"
        "Floating rate |  | 50 | 50 | 50 | 50 | 50 | 50 | 300 | 295\n"
        "Total debt-Consolidated Centers | $ | 150 | 150 | 150 | 150 | 150 | 150 | 900 | 885"
    )
    assert _eval_eps(text).legs == ("form:gold:debt_maturity",)


def test_lease_ladder_without_thereafter_header_is_not_debt_maturity():
    text = (
        "2017 | $ | 6,576\n"
        "2018 |  | 5,173\n"
        "2019 |  | 4,052\n"
        "2020 |  | 3,038\n"
        "Thereafter |  | 338"
    )
    assert not _eval_eps(text).fired


def test_leg_gold_inventory():
    text = (
        " | December 31, 2017 | December 31, 2016\n"
        "Raw materials | $ | 10,000 | $ | 9,000\n"
        "Work in process |  | 5,000 |  | 4,500\n"
        "Finished goods |  | 8,000 |  | 7,500\n"
        "Reserve for obsolescence |  | (500) |  | (400)"
    )
    assert _eval_int(text).legs == ("form:gold:inventory",)


def test_single_inventory_component_is_not_inventory():
    text = (
        " | December 31, 2017 | December 31, 2016\n"
        "Raw materials | $ | 10,000 | $ | 9,000\n"
        "Total |  | 10,000 |  | 9,000"
    )
    assert not _eval_int(text).fired


def test_leg_movement_detail_change_bridge():
    text = (
        " | September 30, 2024 | September 30, 2025\n"
        "Reason for the change |  | \n"
        "Higher (lower) earnings from renewable projects |  | 100\n"
        "Higher (lower) operating earning |  | 50\n"
        "Lower (higher) other expense |  | (20)\n"
        "Lower (higher) tax expense |  | (10)"
    )
    assert _eval_eps(text).legs == ("form:movement-detail",)


def test_leg_movement_detail_tax_bridge():
    text = (
        " | 2023 | 2022\n"
        "Total before tax | $ | 100 | $ | 90\n"
        "Tax benefit |  | (20) |  | (18)\n"
        "Net of tax |  | 80 |  | 72"
    )
    assert _eval_int(text).legs == ("form:movement-detail",)


def test_single_direction_stub_is_not_movement_detail():
    text = (
        " | September 30, 2024 | September 30, 2025\n"
        "Higher (lower) earnings from renewable projects |  | 100\n"
        "Total |  | 100"
    )
    assert not _eval_eps(text).fired


def test_leg_fragment_single_row():
    text = "Anti-dilutive shares from equity-based awards | 50,320 | 50,012 | 136,323"
    assert _eval_eps(text).legs == ("form:fragment",)


def test_leg_fragment_prose_rows():
    first = (
        "The following table sets forth the number of shares that were "
        "excluded from the computation of diluted earnings per share "
        "because their inclusion would have been anti-dilutive in nature "
        "for the periods presented herein and in the notes thereto."
    )
    second = (
        "Shares issuable upon the exercise of outstanding stock options "
        "and the vesting of restricted stock units that were not included "
        "in the diluted share count because the exercise price exceeded "
        "the average market price during the reporting period presented."
    )
    text = f"{first} | 0.4\n{second} | 0.3"
    assert _eval_eps(text).legs == ("form:fragment",)


def test_two_short_rows_are_not_fragment():
    text = (
        " | 2019 | 2018 | 2017 | 2016 | 2015\n"
        "(In millions) | 10 | 20 | 30 | 40 | 50"
    )
    assert not _eval_int(text).fired


def test_leg_summary_columns():
    text = (
        " | 1st | 2nd | 3rd | 4th | 1st | 2nd | 3rd | 4th\n"
        "Net income | $ | 100 | 110 | 120 | 130 | 90 | 95 | 105 | 115\n"
        "Diluted earnings per share | $ | 0.50 | 0.55 | 0.60 | 0.65 | 0.45 | 0.48 | 0.52 | 0.58"
    )
    assert _eval_eps(text, ("2009 Quarters",)).legs == ("form:summary-columns",)


def test_quarters_caption_without_ordinals_is_not_summary_columns():
    text = (
        " | 2009 | 2008\n"
        "Net income | $ | 460 | $ | 405\n"
        "Diluted earnings per share | $ | 2.30 | $ | 2.03"
    )
    assert not _eval_eps(text, ("2009 Quarters",)).fired


def test_leg_ladder_detail():
    text = (
        " | Amount\n"
        "Due in one year or less | $ | 100\n"
        "Due in one to two years |  | 200\n"
        "Total |  | 300"
    )
    assert _eval_eps(text).legs == ("form:ladder-detail",)


def test_single_due_in_stub_is_not_ladder_detail():
    text = (
        " | Amount\n"
        "Due in one year or less | $ | 100\n"
        "Other |  | 50\n"
        "Total |  | 150"
    )
    assert not _eval_eps(text).fired


def test_leg_shape_fair_value_levels():
    text = (
        "Level Input: Input Definition: |  | \n"
        "Level I | $ | 100\n"
        "Level II |  | 200\n"
        "Level III |  | 300"
    )
    assert _eval_eps(text).legs == ("form:shape:fair_value",)


def test_leg_shape_fair_value_headers():
    text = (
        " | Carrying Value | Fair Value | Carrying Value | Fair Value\n"
        "Mortgage loans receivable | $ | 100 | 110 | 90 | 95\n"
        "Bank borrowings |  | 50 | 55 | 45 | 48\n"
        "Senior unsecured notes |  | 200 | 210 | 190 | 195"
    )
    assert _eval_eps(text).legs == ("form:shape:fair_value",)


def test_single_level_stub_is_not_fair_value():
    text = (
        "Level Input: Input Definition: |  | \n"
        "Level I | $ | 100\n"
        "Other |  | 50"
    )
    assert not _eval_eps(text).fired


def test_leg_restatement_recast():
    text = (
        " | Three months ended December 31, 2014\n"
        "Three months ended December 31, 2014, as reported | $ | 100\n"
        "Impact of tax law change |  | (10)\n"
        "Three months ended December 31, 2014, as adjusted |  | 90"
    )
    assert _eval_eps(text).legs == ("form:restatement-recast",)


def test_as_reported_without_as_adjusted_is_not_recast():
    text = (
        " | 2006\n"
        "Net income as reported | $ | 100\n"
        "Earnings per share as reported | $ | 1.00\n"
        "Earnings per share pro forma | $ | 0.95"
    )
    assert not _eval_eps(text).fired


def test_recast_cell_does_not_refuse_intangibles():
    text = (
        " | Three months ended December 31, 2014\n"
        "Three months ended December 31, 2014, as reported | $ | 100\n"
        "Impact of tax law change |  | (10)\n"
        "Three months ended December 31, 2014, as adjusted |  | 90"
    )
    assert not _eval_int(text).fired


def test_goodwill_rollforward_balance_bookends_are_clear():
    text = (
        " | Amount\n"
        "Balance, December 31, 2017 | $ | 1,000\n"
        "Goodwill measurement period adjustment |  | 50\n"
        "Goodwill acquired |  | 200\n"
        "Goodwill related to disposed asset group |  | (100)\n"
        "Foreign currency translation |  | 10\n"
        "Balance, December 31, 2018 |  | 1,160"
    )
    assert not _eval_int(text).fired


def test_related_party_roster_is_not_furniture():
    text = (
        "Related Parties |  | Relationship\n"
        "Haipeng Wang |  | Chairman, President and CEO of the Company\n"
        "Harbin Donglin |  | Director"
    )
    assert not _eval(text).fired


def test_notes_payable_past_due_is_not_composition():
    text = (
        " | September 30, 2014 | June 30, 2014\n"
        "Notes payable to director/shareholder, interest rate of 8%,"
        " unsecured and payable on December 31, 2012 (past due) |  | 3,500\n"
        "Notes payable to shareholder, interest rate of 10%,"
        " unsecured and payable on July 31, 2004 |  | 5,000"
    )
    assert not _eval(text).fired


def test_segment_revenue_without_change_columns_is_clear():
    text = (
        "Summary of revenues |  |  | \n"
        " | 2021 | 2020\n"
        "Dalrada Health | $ | 15,309\n"
        "Prakat |  | 47,500\n"
        "Total | $ | 66,033"
    )
    assert not _eval(text).fired


def test_loan_rollforward_is_clear():
    text = (
        " | 2018 | 2017\n"
        "Beginning balance | $ | 76,835\n"
        "New loans |  | 24,957\n"
        "Loan repayments |  | (7,786)\n"
        "Ending balance | $ | 94,006"
    )
    assert not _eval(text).fired


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
