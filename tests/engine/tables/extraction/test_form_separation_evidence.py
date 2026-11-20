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


# ---------------- broader D2: payment/option schedules ----------------


def test_leg_payment_schedule_dividend_dates():
    text = (
        " | Dividend |  |  | \n"
        " | Payment Date | Record Date | Amount | \n"
        " | Dividend |  |  | \n"
        "Dividends payable, January 1, 2008 | $ | 20 | $ | 21\n"
        "Dividends declared |  | 100 |  | 105\n"
        "Dividends paid |  | (90) |  | (95)"
    )
    assert _eval_eps(text).legs == ("form:supplemental-schedule",)


def test_leg_payment_schedule_distribution_amount():
    text = (
        " |  | Three Months Ended |  |  |  | Six Months Ended |  |  |  | \n"
        " |  | June 30, |  |  |  | June 30, |  |  |  | \n"
        " | Dividend Payments on Common Stock | 2022 |  | 2021 |  | 2022 |  | 2021 |  | \n"
        " | Per Share | $ | 0.54 | $ | 0.51 | $ | 1.08 | $ | 1.02 | \n"
        " | In Millions | $ | 270 | $ | 258 | $ | 541 | $ | 516 | "
    )
    assert _eval_eps(text).legs == ("form:supplemental-schedule",)


def test_dividend_without_payment_headers_is_not_supplemental():
    text = (
        " | 2022 | 2021\n"
        "Dividends declared | $ | 100 | $ | 90\n"
        "Dividends paid |  | (80) |  | (70)"
    )
    assert not _eval_eps(text).fired


def test_payment_schedule_does_not_refuse_related_party():
    text = (
        " | Dividend |  |  | \n"
        " | Payment Date | Record Date | Amount | \n"
        "Dividends payable | $ | 20 | $ | 21"
    )
    assert not _eval(text).fired


def test_leg_option_schedule():
    text = (
        " | Years Ended December 31, |  |  |  |  | \n"
        " | 2011 |  | 2010 |  | 2009 | \n"
        "Number of options |  | 0 |  | 0 |  | 755,494\n"
        "Ranges of option purchase prices | $ | 0 | $ | 0 | $ | 18.33-20.36"
    )
    assert _eval_eps(text).legs == ("form:supplemental-schedule",)


def test_options_stub_without_count_or_price_is_not_supplemental():
    text = (
        " | 2011 | 2010\n"
        "Stock options |  | 100 |  | 90\n"
        "Total |  | 100 |  | 90"
    )
    assert not _eval_eps(text).fired


# ---------------- broader D2: condensed summaries ----------------


def test_leg_condensed_summary_statutory_capital():
    text = (
        " | 2007 |  | 2006 | \n"
        " |  |  |  | \n"
        " | (In millions) |  |  | \n"
        "Combined statutory capital and surplus: |  |  |  | \n"
        "Life insurance operations | $ | 29,416 |  | $ | 28,189\n"
        "Property insurance operations |  | 5,692 |  |  | 5,480\n"
        "Total combined statutory capital and surplus | $ | 35,108 |  | $ | 33,669"
    )
    assert _eval_eps(text).legs == ("form:statement-summary",)


def test_leg_condensed_summary_continuing_operations():
    text = (
        " | 2007 |  | 2006 | \n"
        " | (In millions, except per share data) |  |  | \n"
        " | Earnings per share: |  |  | \n"
        "Continuing operations: |  |  |  | \n"
        "Utility and Corporate Services |  | 304.8 |  |  | 305.6\n"
        "Non-regulated and parent |  | 20.1 |  |  | 26.5\n"
        "Income from continuing operations |  | 324.9 |  |  | 332.1\n"
        "Loss from discontinued operations |  | (5.1) |  |  | 17.5\n"
        "Net income | $ | 319.8 |  | $ | 349.6"
    )
    assert _eval_eps(text).legs == ("form:statement-summary",)


def test_condensed_summary_with_own_frame_is_clear():
    text = (
        " | 2007 |  | 2006 | \n"
        " | (In thousands, except per share data) |  |  | \n"
        "Net (loss) income: |  |  |  |  |  |  | \n"
        "Net (loss) income from continuing operations | $ | (144,680) |  | $ | 374,300\n"
        "Net income from discontinued operations, net of tax |  | 3,821 |  |  | 4,715\n"
        "Net (loss) income | $ | (139,502) |  | $ | 379,015\n"
        "Weighted-average shares: |  |  |  |  |  |  | \n"
        "Weighted-average common shares outstanding |  | 237,707 |  |  | 244,421"
    )
    assert not _eval_eps(text).fired


def test_condensed_summary_long_table_is_clear():
    text = (
        " | 2010 | 2009\n"
        "Income from continuing operations | $ | 100 | $ | 90\n"
        "Loss from discontinued operations |  | (5) |  | (4)\n"
        "Net income |  | 95 |  | 86\n"
        "Other income |  | 10 |  | 9\n"
        "Other expense |  | (2) |  | (1)\n"
        "Gain on sale |  | 3 |  | 2\n"
        "Tax expense |  | (1) |  | (1)\n"
        "Total |  | 105 |  | 95"
    )
    assert not _eval_eps(text).fired


# ---------------- broader D2: percentage schedules ----------------


def test_leg_percentage_schedule():
    text = (
        " | Shares Beneficially Owned |  |  | \n"
        "Name of Beneficial Owner | Number |  | Percentage | \n"
        "Directors and Executive Officers |  |  |  |  | \n"
        "Jeffrey Crowe (1) |  | 12,705,505 |  | 17.2\n"
        "Daniel Ciporin (2) |  | 12,512,798 |  | 16.9\n"
        "Rebecca Lynn (3) |  | 7,122,876 |  | 9.7\n"
        "All executive officers and directors as a group |  | 43,049,419 |  | 56.8"
    )
    assert _eval_eps(text).legs == ("form:percentage-rows",)


def test_percentage_schedule_without_header_is_clear():
    text = (
        " | Shares Beneficially Owned |  |  | \n"
        "Name of Beneficial Owner | Number |  | Amount | \n"
        "Jeffrey Crowe (1) |  | 12,705,505 |  | 17.2\n"
        "Daniel Ciporin (2) |  | 12,512,798 |  | 16.9"
    )
    assert not _eval_eps(text).fired


# ---------------- broader D2: generalized composition ----------------


def test_leg_generalized_composition_share_equivalents():
    text = (
        " | As of December 31, | \n"
        " | 2025 | 2024\n"
        "Anti-dilutive common stock equivalents: |  | \n"
        "October 2024 Common Warrants | 2,398,414 | 2,398,414\n"
        "March 2025 Common Warrants | 8,316,882 | 0\n"
        "Stock options outstanding | 2,429,064 | 1,160,251\n"
        "Unvested RSAs | 0 | 40,137\n"
        "Unvested RSUs | 257,400 | 0\n"
        "Total anti-dilutive common stock equivalents | 16,478,681 | 3,598,802"
    )
    assert _eval_eps(text).legs == ("form:composition",)


def test_leg_generalized_composition_carrying_value():
    text = (
        " | As of |  |  |  |  | \n"
        " | July 31, 2016 |  |  | January 31, 2016 |  | \n"
        "Liability component : |  |  |  |  |  | \n"
        "Principal (1) | $ | 1,150,000 |  | $ | 1,150,000 | \n"
        "Less: debt discount, net (2) | (42,526) |  |  | (54,941) |  | \n"
        "Less: debt issuance cost (3) | (5,324) |  |  | (6,962) |  | \n"
        "Net carrying amount | $ | 1,102,150 |  | $ | 1,088,097 | "
    )
    assert _eval_int(text).legs == ("form:composition",)


def test_leg_generalized_composition_goodwill_segments():
    text = (
        " | March 31, |  | June 30, | \n"
        " | 2021 |  | 2020 | \n"
        " |  |  |  | \n"
        "Goodwill - Original Sprout | $ | 416,817 | $ | 416,817\n"
        "Goodwill - Gourmet Foods |  | 275,311 |  | 147,628\n"
        "Goodwill - Brigadier |  | 351,345 |  | 351,345\n"
        "Total | $ | 1,043,473 | $ | 915,790"
    )
    assert _eval_int(text).legs == ("form:composition",)


def test_leg_generalized_composition_geography():
    text = (
        " | October 31, |  | January 31, |  | October 31, | \n"
        " | 2020 |  | 2020 |  | 2019 | \n"
        "United States | $ | 15,884 | $ | 18,852 | $ | 19,613\n"
        "International |  | 8,118 |  | 10,386 |  | 9,662\n"
        "Consolidated total | $ | 24,002 | $ | 29,238 | $ | 29,275"
    )
    assert _eval_int(text).legs == ("form:composition",)


def test_generalized_composition_with_own_frame_is_clear():
    text = (
        " | For the Three Months Ended September 30, |  |  |  | For the Nine Months Ended September 30, |  |  |  | \n"
        " | 2019 |  | 2018 |  | 2019 |  | 2018 | \n"
        "Numerator (basic and diluted): |  |  |  |  |  |  |  | \n"
        "Net income | $ | 391,293 | $ | 366,151 | $ | 1,066,126 | $ | 1,024,130\n"
        "Denominator: |  |  |  |  |  |  |  | \n"
        "Weighted-average common shares outstanding - basic | 76,172 |  | 80,593 |  | 77,415 |  | 81,939\n"
        "Effect of stock options (1) | 797 |  | 817 |  | 805 |  | 902\n"
        "Stock options (1) | 207 |  | 650 |  | 214 |  | 232"
    )
    assert not _eval_eps(text).fired


def test_generalized_composition_header_frame_cells_is_clear():
    text = (
        " | For the Year Ended October 31, 2008 |  |  |  |  | \n"
        " | Numerator |  | Denominator |  | Per Share | \n"
        " | (Income) |  | (Shares) |  | Amount | \n"
        "Basic earnings per share | $ | 15,904 |  | 37,274 | $ | 0.43\n"
        "Effect of dilutive securities: |  |  |  |  |  | \n"
        "Common stock equivalents arising from stock options |  | — |  | 6 |  | \n"
        "Restricted stock |  | — |  | 13 |  | \n"
        "Diluted earnings per share | $ | 15,904 |  | 38,528 | $ | 0.41"
    )
    assert not _eval_eps(text).fired


def test_generalized_composition_stub_header_frame_is_clear():
    text = (
        " | YEAR ENDED DECEMBER 31, 2014 |  |  |  |  | \n"
        "(dollars in thousands) | Income\n"
        "(Numerator) |  | Shares\n"
        "(Denominator) |  | Per-Share\n"
        "Amount | \n"
        "Basic EPS: |  |  |  |  |  | \n"
        "Net income | $ | 7,122 |  | 7,938,052 | $ | 0.90\n"
        "Effect of dilutive securities: |  |  |  |  |  | \n"
        "Stock options |  | — |  | 4,822 |  | \n"
        "Non-vested restricted stock |  | — |  | 49,857 |  | \n"
        "Diluted EPS: |  |  |  |  |  | \n"
        "Net income per diluted share | $ | 7,122 |  | 7,992,731 | $ | 0.89"
    )
    assert not _eval_eps(text).fired


def test_generalized_composition_stacked_shares_header_is_clear():
    text = (
        " | Three Months Ended September 30, |  |  |  |  |  | \n"
        " | 2007 |  |  |  | 2008 |  | \n"
        " | Income |  | Weighted\n"
        "Average\n"
        "Shares |  | Per-Share |  | Income |  | Weighted\n"
        "Average\n"
        "Shares |  | Per-Share | \n"
        "Earnings per share - basic |  |  |  |  |  |  | \n"
        "Income available to common stockholders | $ | 47,318 |  | 27,733 | $ | 1.71\n"
        "Effect of dilutive securities: |  |  |  |  |  |  | \n"
        "Convertible senior notes |  | 737 |  | 4,900 |  |  | \n"
        "Options and warrants |  | — |  | 260 |  |  | \n"
        "Unvested restricted stock grants |  | — |  | 252 |  |  | \n"
        "Earnings per share - diluted |  |  |  |  |  |  | \n"
        "Income available to common stockholders plus assumed exercises and conversion | $ | 48,055 |  | 33,145 | $ | 1.45"
    )
    assert not _eval_eps(text).fired


def test_generalized_composition_descriptive_frame_header_fires():
    text = (
        " | Weighted Average Shares Excluded from Denominator |  |  | \n"
        " | For the Three Months Ended June 30, |  | For the Six Months Ended June 30, | \n"
        " | 2025 | 2024 | 2025 | 2024\n"
        "Stock options | 1,200 | 1,100 | 1,200 | 1,100\n"
        "Restricted stock units | 300 | 250 | 300 | 250\n"
        "Total shares excluded | 1,500 | 1,350 | 1,500 | 1,350"
    )
    assert _eval_eps(text).legs == ("form:composition",)


def test_generalized_composition_add_deduct_walk_is_clear():
    text = (
        " | 2005 |  |  | 2004 |  | \n"
        " |  |  |  |  |  | \n"
        "Net income as reported | $ | 126,658 |  | $ | 90,100 | \n"
        "Add: stock-based employee compensation expense included in reported net income, net of taxes |  | 6,299 |  |  | 4,071 | \n"
        "Deduct: total stock-based employee compensation expense determined under fair value based methods for all awards, net of taxes |  | (9,282) |  |  | (8,289) | \n"
        "Net income - pro forma | $ | 123,675 |  | $ | 85,882 | "
    )
    assert not _eval_eps(text).fired


def test_generalized_composition_single_component_is_clear():
    text = (
        " | Net |  |  |  |  |  | \n"
        " | Earnings |  |  | Weighted |  |  | \n"
        " | Applicable to |  |  | Average |  | Net | \n"
        " | Common |  |  | Common Shares |  | Earnings | \n"
        " | Stockholders |  |  | Outstanding |  | per Share | \n"
        "Earnings from continuing operations | $ | 574 |  |  |  |  | \n"
        "Basic earnings per share |  | 572 |  |  | 444 | $ | 1.29\n"
        "Effect of outstanding stock options |  | 0 |  |  | 6 |  | \n"
        "Diluted earnings per share | $ | 572 |  |  | 450 | $ | 1.27"
    )
    assert not _eval_eps(text).fired


def test_goodwill_walk_narrow_does_not_refuse_related_party():
    text = (
        "Balance as of December 31, 2013 |  | 196,395 | \n"
        "Goodwill acquired through the acquisition of Westchester Imaging |  | 231 | \n"
        "Balance as of December 31, 2015 | $ | 239,408 | "
    )
    assert not _eval(text).fired


# ---------------- broader D2: goodwill walks + non-GAAP bridge ----------------


def test_leg_goodwill_walk_acquisition():
    text = (
        "Balance as of December 31, 2013 |  | 196,395 | \n"
        "Goodwill acquired through the acquisition of Westchester Imaging |  | 231 | \n"
        "Goodwill acquired through the acquisition of Garden State Radiology |  | 50 | \n"
        "Goodwill disposed through the sale of New Jersey Imaging Partners |  | (18,833) | \n"
        "Balance as of December 31, 2015 | $ | 239,408 | "
    )
    assert _eval_int(text).legs == ("form:movement-detail",)


def test_leg_goodwill_walk_franchisee_sale():
    text = (
        " | Jack in the Box |  | Del Taco |  | Total | \n"
        "Balance at October 2, 2022 | $ | 136,099 | $ | 230,722 | $ | 366,821\n"
        "Sale of Del Taco company-operated restaurants to franchisees | 0 |  | (7,238) |  | (7,238) | \n"
        "Sale of Jack in the Box company-operated restaurants to franchisees | (72) |  | 0 |  | (72) | \n"
        "Reclassified to assets held for sale | 0 |  | (5,900) |  | (5,900) | \n"
        "Balance at April 16, 2023 | $ | 136,027 | $ | 217,584 | $ | 353,611"
    )
    assert _eval_int(text).legs == ("form:movement-detail",)


def test_goodwill_walk_bare_acquired_is_not_movement():
    text = (
        " | 2019 |  | 2018 | \n"
        "Balance, January 1 | $ | 445,355 | $ | 445,355\n"
        "Goodwill acquired | 97,844 |  | 0 | \n"
        "Measurement period adjustment | 719 |  | $ | 0\n"
        "Balance, December 31 | $ | 543,918 | $ | 445,355"
    )
    assert not _eval_int(text).fired


def test_leg_nongaap_bridge():
    text = (
        " | For the year ended | \n"
        " | December 31, 2019 | \n"
        "EPS (GAAP) | $ | 3.00\n"
        "Plus/(less): Pre-tax adjustments: Securities gains, unrealized gains on equity investments, corporate development and restructuring expense, recovery of fraud loss | 0.91 | \n"
        "(Plus) less: Tax impact of pre-tax adjustments | (0.17) | \n"
        "Core EPS (non-GAAP) | $ | 3.74"
    )
    assert _eval_eps(text).legs == ("form:movement-detail",)


def test_nongaap_bridge_without_core_eps_is_clear():
    text = (
        " | For the year ended | \n"
        " | December 31, 2019 | \n"
        "EPS (GAAP) | $ | 3.00\n"
        "Plus/(less): Pre-tax adjustments | 0.91 | \n"
        "(Plus) less: Tax impact of pre-tax adjustments | (0.17) | \n"
        "Adjusted EPS | $ | 3.74"
    )
    assert not _eval_eps(text).fired


# ---------------- broader D2: wrapped fair value + single-row fragment ----------------


def test_leg_fair_value_wrapped():
    text = (
        " | At September 30, 2019 |  |  |  |  | At December 31, 2018 |  |  |  | \n"
        " | Carrying |  | Fair |  |  | Carrying |  | Fair |  | \n"
        " | Value |  | Value |  |  | Value |  | Value |  | \n"
        "Mortgage loans receivable | $ | 253,186 | $ | 310,842 |  | $ | 242,939 | $ | 295,492\n"
        "Bank borrowings |  | 165,400 |  | 165,400 |  |  | 112,000 |  | 112,000\n"
        "Senior unsecured notes, net of debt issue costs |  | 518,469 |  | 537,739 |  |  | 533,029 |  | 508,613"
    )
    assert _eval_eps(text).legs == ("form:shape:fair_value",)


def test_fair_value_wrapped_without_carrying_is_clear():
    text = (
        " | At September 30, 2019 |  |  |  | \n"
        " | Fair |  |  |  | \n"
        " | Value |  |  |  | \n"
        "Mortgage loans receivable | $ | 253,186 | $ | 310,842\n"
        "Bank borrowings |  | 165,400 |  | 165,400"
    )
    assert not _eval_eps(text).fired


def test_leg_single_data_row_fragment_share_awards():
    text = (
        "(in millions) | Fiscal 2017 | Fiscal 2016 | Fiscal 2015\n"
        "Share awards | 0.1 | 0.1 | 0"
    )
    assert _eval_eps(text).legs == ("form:fragment",)


def test_leg_single_data_row_fragment_goodwill():
    text = (
        " | December 31, |  |  | \n"
        " | 2023 |  | 2022 | \n"
        "Goodwill | $ | 0 | $ | 49,786"
    )
    assert _eval_int(text).legs == ("form:fragment",)


def test_single_data_row_amortization_is_not_fragment():
    text = (
        " | December 31, |  |  | \n"
        " | 2023 |  | 2022 | \n"
        "Amortization | $ | 100 | $ | 90"
    )
    assert not _eval_int(text).fired


def test_single_data_row_with_own_frame_is_not_fragment():
    text = (
        " | 2023 | 2022\n"
        "Weighted average shares outstanding | 100,000 | 90,000"
    )
    assert not _eval_eps(text).fired


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
