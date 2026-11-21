"""Form separation: generalized composition."""

from __future__ import annotations

from .form_separation_fixtures import _eval, _eval_eps, _eval_int

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
