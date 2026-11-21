"""Form separation priced legs: gold forms."""

from __future__ import annotations

from .form_separation_fixtures import _eval, _eval_eps, _eval_int

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
