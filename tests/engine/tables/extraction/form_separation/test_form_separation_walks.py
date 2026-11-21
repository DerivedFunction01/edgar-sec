"""Form separation: goodwill walks, non-GAAP bridge, wrapped forms."""

from __future__ import annotations

from .form_separation_fixtures import _eval_eps, _eval_int

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
        " | December 31, |  |  | \n | 2023 |  | 2022 | \nGoodwill | $ | 0 | $ | 49,786"
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
    text = " | 2023 | 2022\nWeighted average shares outstanding | 100,000 | 90,000"
    assert not _eval_eps(text).fired
