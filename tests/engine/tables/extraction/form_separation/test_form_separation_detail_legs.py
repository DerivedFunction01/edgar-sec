"""Form separation priced legs: detail forms and clear cases."""

from __future__ import annotations

from .form_separation_fixtures import _eval, _eval_eps, _eval_int


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
    text = " | 2019 | 2018 | 2017 | 2016 | 2015\n(In millions) | 10 | 20 | 30 | 40 | 50"
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
    text = " | Amount\nDue in one year or less | $ | 100\nOther |  | 50\nTotal |  | 150"
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
    text = "Level Input: Input Definition: |  | \nLevel I | $ | 100\nOther |  | 50"
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
