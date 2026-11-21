"""Form separation (TEST_FORM_SEPARATION): composition, dispatch, gate."""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.cascade.competition import compete
from edgar_sec.engine.tables.extraction.cascade.geometry_text import GeometryText
from edgar_sec.engine.tables.extraction.core.context import TableContext
from edgar_sec.engine.tables.extraction.form_tests.form_tests import (
    FormTestOutcome,
    evaluate_form_tests,
)
from edgar_sec.engine.tables.extraction.cascade.geometry_scoring import FamilyScore
from edgar_sec.engine.tables.extraction.core.profiles import (
    TEST_FORM_SEPARATION,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import structure_table
from tests.engine.tables.extraction.evidence.test_form_separation_evidence import (
    _eval,
    _eval_eps,
    _eval_int,
)


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
