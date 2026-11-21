"""Form separation: payment/option schedules and condensed summaries."""

from __future__ import annotations

from .form_separation_fixtures import _eval, _eval_eps

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
    text = " | 2011 | 2010\nStock options |  | 100 |  | 90\nTotal |  | 100 |  | 90"
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
