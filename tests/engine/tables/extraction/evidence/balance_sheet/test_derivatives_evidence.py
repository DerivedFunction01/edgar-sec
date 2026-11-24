"""Derivatives-evidence gate: registry data, specimen shapes, seat."""

from __future__ import annotations

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
from edgar_sec.engine.tables.extraction.evidence.balance_sheet.derivatives_evidence import (
    DerivativesText,
    _is_period_label,
    derivatives_evidence_for_geometry,
    derivatives_subject_for_geometry,
    evaluate_derivatives_evidence,
    evaluate_form_test_derivatives,
)
from edgar_sec.engine.tables.extraction.specs.families.derivatives_evidence_specs import (
    DERIVATIVES_EVIDENCE_SPECS,
    DERIVATIVES_EVIDENCE_SPECS_BY_TEST_ID,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_specs import (
    FORM_TEST_SPECS,
)
from edgar_sec.engine.tables.extraction.core.subjects.profile_constants import (
    TEST_DERIVATIVES_EVIDENCE,
)
from edgar_sec.engine.tables.extraction.core.subjects.profiles import (
    profile_for,
)
from edgar_sec.engine.tables.extraction.core.subjects.signature_profiles import (
    SignatureTerm,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import structure_table

SPEC = DERIVATIVES_EVIDENCE_SPECS["derivatives_hedging"]


def _verdict(geometry: GeometryText):
    return derivatives_evidence_for_geometry(geometry)


def _table(rows: tuple[tuple[str, ...], ...], prose_before: str = ""):
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
    context = TableContext(geometry=geometry, prose_before=prose_before)
    return structure_table(context)


def test_gate_is_declared_as_form_test_data():
    entry = next(s for s in FORM_TEST_SPECS if s.family == "derivatives_hedging")
    assert entry.kind == TEST_DERIVATIVES_EVIDENCE
    assert entry.points == 0.0
    assert DERIVATIVES_EVIDENCE_SPECS_BY_TEST_ID[entry.test_id] is SPEC
    assert TEST_DERIVATIVES_EVIDENCE in profile_for("derivatives_hedging").form_tests


def test_u_designation_notional_table_admits_strong():
    verdict = _verdict(
        GeometryText(
            caption="Derivatives",
            stubs=(
                "Interest rate swaps",
                "Foreign exchange contracts",
                "Commodity contracts",
            ),
            headers=("Notional Amount", "Fair Value"),
        )
    )
    assert verdict.admitted and verdict.evidence_class == "U" and verdict.strong


def test_u_period_listing_admits_strong():
    verdict = _verdict(
        GeometryText(
            stubs=(
                "Natural Gas Basis Swaps:",
                "April - December 2026",
                "January - December 2027",
                "January - December 2028",
                "Total",
            ),
            headers=("Notional Amount", "Average Fixed Price", "Fair Value"),
        )
    )
    assert verdict.admitted and verdict.evidence_class == "U" and verdict.strong


def test_u_price_swap_listing_over_full_grid():
    table = _table(
        (
            ("Contract Period", "Contract Type", "Notional Volume", "Fixed Price"),
            ("Apr 10 - Dec 10", "Price swap contracts", "25", "$4.13"),
            ("Jan 11 - Dec 11", "Price swap contracts", "25", "$4.26"),
            ("Jan 12 - Dec 12", "Price swap contracts", "25", "$4.39"),
        )
    )
    spec = next(s for s in FORM_TEST_SPECS if s.family == "derivatives_hedging")
    verdict = evaluate_form_test_derivatives(table, spec)
    assert verdict.admitted and verdict.evidence_class == "U" and verdict.strong


def test_a_designation_gain_loss_table_admits():
    verdict = _verdict(
        GeometryText(
            leadin="The following table presents the pre-tax gains (losses) "
            "for derivative instruments designated as cash flow hedges:",
            stubs=(
                "Derivatives designated as hedging instruments",
                "Interest rate contracts",
                "Foreign exchange contracts",
                "Commodity contracts",
            ),
            headers=(
                "Amount of Gain (Loss) Recognized in OCI",
                "Location of Gain (Loss) Reclassified from AOCI",
            ),
        )
    )
    assert verdict.admitted and verdict.strong


def test_leadin_only_designation_without_anchor_refuses():
    verdict = _verdict(
        GeometryText(
            caption="March 31,",
            leadin="Our objective for holding derivative financial "
            "instruments is to manage interest rate risk through interest "
            "rate swap agreements. Derivatives that are not designated as "
            "cash flow hedges are adjusted to fair value through income. "
            "See Note 11, Derivatives.",
            stubs=(
                "Truck and trailer parts and accessories",
                "Hitches and towing components",
                "Moving supplies and propane",
                "Subtotal",
                "Less: LIFO reserves",
                "Total",
            ),
            headers=("March 31,", "2021", "2020", "(In thousands)"),
        )
    )
    assert not verdict.admitted


def test_leadin_designation_with_subject_anchor_admits():
    verdict = _verdict(
        GeometryText(
            leadin="The Company uses derivative financial instruments "
            "designated as cash flow hedges; the following table "
            "summarizes their positions at period end:",
            stubs=("Interest rate contracts", "Foreign exchange contracts"),
            headers=("Notional Amount", "Amount of Gain (Loss) Recognized"),
        )
    )
    assert verdict.admitted and verdict.evidence_class == "A"


def test_a_offsetting_frontier_admits():
    verdict = _verdict(
        GeometryText(
            caption="Gross Amounts Not Offset in the Condensed Consolidated "
            "Balance Sheet",
            stubs=("Derivative assets", "Reverse repurchase agreements"),
            headers=(
                "Gross Amounts of Recognized Assets",
                "Gross Amounts Offset",
                "Net Amounts Presented",
            ),
        )
    )
    assert verdict.admitted and verdict.strong


def test_a_effects_frontier_admits():
    verdict = _verdict(
        GeometryText(
            leadin="The table below shows the effect of our derivative "
            "financial instruments designated as cash flow hedges for the "
            "three months ended:",
            stubs=(
                "Effects of Cash Flow Hedges",
                "Amount of loss reclassified from accumulated other "
                "comprehensive income (loss) into interest expense",
            ),
        )
    )
    assert verdict.admitted and verdict.strong


def test_a_call_put_boundary_admits_not_comp_blocked():
    verdict = _verdict(
        GeometryText(
            stubs=("Call option", "Put option"),
            headers=(
                "Description",
                "Counterparty",
                "Number of shares",
                "Notional amount",
                "Exercise price",
                "Expiration date",
                "Value",
            ),
        )
    )
    assert verdict.admitted and verdict.evidence_class == "A"


def test_a_position_anchors_over_full_grid():
    table = _table(
        (
            ("", "Notional Amounts", "Fair Market Value"),
            ("Euros", "1,000", "50"),
            ("Pounds sterling", "2,000", "75"),
        ),
        prose_before="Gains and losses on foreign exchange contracts are "
        "recorded in other income and expenses, net.",
    )
    spec = next(s for s in FORM_TEST_SPECS if s.family == "derivatives_hedging")
    verdict = evaluate_form_test_derivatives(table, spec)
    assert verdict.admitted and verdict.evidence_class == "A" and verdict.strong


def test_a_rate_cap_anchor_over_full_grid():
    table = _table(
        (
            (
                "Date Purchased",
                "Notional Amount",
                "Effective Capped Rate",
                "Maturity Date",
                "Purchase Price",
                "Counterparty",
            ),
            ("April 2009", "$20,000", "6.00%", "April 2014", "$55", "Bank"),
        )
    )
    spec = next(s for s in FORM_TEST_SPECS if s.family == "derivatives_hedging")
    verdict = evaluate_form_test_derivatives(table, spec)
    assert verdict.admitted and verdict.evidence_class == "A"


def test_c_context_contract_volumes_admit():
    verdict = _verdict(
        GeometryText(
            leadin="Alcoa enters into futures and option contracts to reduce "
            "the volatility in the price of anticipated sales.",
            stubs=(
                "Aluminum contracts (kmt)",
                "Energy contracts (megawatt hours)",
                "Foreign exchange contracts",
            ),
        )
    )
    assert verdict.admitted and verdict.evidence_class == "C"


def test_n_shapes_refuse():
    shapes = (
        GeometryText(
            caption="Trading Account Securities (dollars in millions)",
            stubs=(
                "Balance, beginning of period",
                "Purchases",
                "Sales and principal payments",
                "Balance, end of period",
            ),
        ),
        GeometryText(
            stubs=(
                "Net income applicable to common shares",
                "Real estate depreciation and amortization",
                "Funds from operations applicable to common shares",
            ),
        ),
        GeometryText(
            stubs=(
                "Euro",
                "British pound",
                "Japanese yen",
                "Other currencies",
                "Total net assets",
            ),
        ),
        GeometryText(
            stubs=(
                "Accrued compensation and benefits",
                "Accrued occupancy",
                "Accrued taxes, other than income taxes",
                "Total accrued expenses and other current liabilities",
            ),
        ),
        GeometryText(
            stubs=(
                "Total loans",
                "Total deposits",
                "Average loans",
                "Average deposits",
            ),
        ),
    )
    for geometry in shapes:
        verdict = _verdict(geometry)
        assert not verdict.admitted and verdict.evidence_class == "N"


def test_e_aoci_components_carve_out_refuses():
    verdict = _verdict(
        GeometryText(
            stubs=(
                "Details about Accumulated Other Comprehensive Income Components",
                "Available-for-sale securities",
                "AOCI related to cash flow hedge relationships",
                "Expense related to derivatives",
            ),
        )
    )
    assert not verdict.admitted and verdict.evidence_class == "E"


def test_e_equity_compensation_refuses():
    verdict = _verdict(
        GeometryText(
            stubs=(
                "Stock options outstanding",
                "Options granted",
                "Restricted stock units",
                "Weighted average exercise price",
            ),
        )
    )
    assert not verdict.admitted and verdict.evidence_class == "E"


def test_c_npns_exclusion_refuses():
    verdict = _verdict(
        GeometryText(
            caption="Commodity Contracts",
            stubs=(
                "Forward contracts for natural gas deliveries under normal "
                "purchases and normal sales",
                "Forward contracts for power deliveries",
            ),
        )
    )
    assert not verdict.admitted and verdict.evidence_class == "C"


def test_gate_removes_no_evidence_claim_in_competition():
    terms = (
        SignatureTerm("derivatives_hedging", "stub", "total assets", 4.0, 5, 0),
        SignatureTerm("derivatives_hedging", "caption", "balance sheet", 4.0, 5, 0),
    )
    geometry = GeometryText(
        caption="Condensed Consolidated Balance Sheets",
        stubs=("Total assets", "Total liabilities", "Total equity"),
    )
    result = compete(geometry, terms)
    assert result.claims == ()
    gated = result.scores["derivatives_hedging"]
    assert any(item.channel == "gate" for item in gated.evidence)


def test_gate_keeps_u_evidence_claim_in_competition():
    terms = (
        SignatureTerm("derivatives_hedging", "stub", "interest rate swaps", 4.0, 5, 0),
    )
    geometry = GeometryText(
        stubs=("Interest rate swaps", "Foreign exchange contracts"),
        headers=("Notional Amount", "Fair Value"),
    )
    result = compete(geometry, terms)
    assert result.claims == ("derivatives_hedging",)


def _subject(geometry: GeometryText):
    return derivatives_subject_for_geometry(geometry)


def test_subject_caption_names_the_subject():
    verdict = _subject(
        GeometryText(
            caption="Derivative Instruments and Hedging Activities",
            stubs=("Cost of revenue", "Gross margin"),
            headers=("2024", "2023"),
        )
    )
    assert verdict.subject


def test_subject_final_paragraph_designation_admits():
    """Priced shape 0001713683-24-000041:29: the introducing
    paragraph itself names the cash flow hedges."""
    verdict = _subject(
        GeometryText(
            leadin="(1) (Gains) losses related to our cash flow hedges "
            "reclassified from AOCI into the condensed consolidated "
            "statement of operations consisted of the following:",
            stubs=("Cost of revenue",),
            headers=("Three Months Ended January 31,", "2024", "2023"),
        )
    )
    assert verdict.subject


def test_subject_background_narrative_only_refuses():
    """Priced shape 0001504461-23-000010:67: derivative prose in an
    earlier paragraph; the introducing paragraph names EBITDA."""
    verdict = _subject(
        GeometryText(
            lead_title="Derivative Instruments",
            leadin="We entered into derivative instrument positions to "
            "secure a margin on barrels per month. The gains and losses "
            "from the derivative instrument positions are recognized in "
            "Adjusted EBITDA.\n"
            "The following table reconciles net income (loss) to EBITDA "
            "and Adjusted EBITDA for the periods indicated:",
            stubs=("Net income (loss)", "Depreciation and amortization"),
            headers=("Three Months Ended December 31,", "2022", "2021"),
        )
    )
    assert not verdict.subject


def test_subject_earlier_section_prose_only_refuses():
    """Priced shape 0001193125-15-089251:32: risk prose in the
    section above; the introducing paragraph names cash flows."""
    verdict = _subject(
        GeometryText(
            leadin="Interest Rate Risk\n"
            "Our exposure to market risk for a change in interest rates "
            "is concentrated in our investment portfolio. Generally, we "
            "do not hedge our exposure to interest rate risk.\n"
            "Principal cash flows and related weighted-average interest "
            "rates by stated maturity dates for the financial instruments "
            "we hold that are sensitive to interest rates at December 31, "
            "2014 are as follows:",
            stubs=("Fixed-maturity and short-term investments:", "2015", "2016"),
            headers=("Principal Cash Flows", "Weighted-Average Interest Rate"),
        )
    )
    assert not verdict.subject


def test_subject_offsetting_form_admits():
    """Priced shape 0000818479-16-000056:123: offsetting framing
    with instrument rows, no derivative word in the framing."""
    verdict = _subject(
        GeometryText(
            caption="Gross Amounts Not Offset in the Consolidated Balance Sheets",
            stubs=(
                "Liabilities",
                "Foreign exchange forward contracts",
                "Commodity contracts",
            ),
            headers=(
                "Gross Amounts Recognized",
                "Gross Amounts Offset in the Consolidated Balance Sheets",
                "Net Amounts Presented",
            ),
        )
    )
    assert verdict.subject and "offsetting" in verdict.detail


def test_subject_notional_header_admits():
    verdict = _subject(
        GeometryText(
            stubs=("Euros", "Pounds sterling"),
            headers=("Notional Amounts", "Fair Market Value"),
        )
    )
    assert verdict.subject


def test_subject_gate_removes_framingless_claim_in_competition():
    terms = (
        SignatureTerm("derivatives_hedging", "stub", "interest rate swaps", 4.0, 5, 0),
        SignatureTerm(
            "derivatives_hedging", "stub", "foreign exchange contracts", 4.0, 5, 0
        ),
    )
    geometry = GeometryText(
        caption="Condensed Consolidated Statements of Operations",
        leadin="The following table presents revenues and expenses "
        "for the periods indicated:",
        stubs=("Interest rate swaps", "Foreign exchange contracts"),
        headers=("2024", "2023"),
    )
    result = compete(geometry, terms)
    assert result.claims == ()
    gated = result.scores["derivatives_hedging"]
    assert any(item.detail.startswith("derivatives subject") for item in gated.evidence)


def test_subject_gate_blocks_reach_without_subject():
    terms = (SignatureTerm("derivatives_hedging", "stub", "swaps", 1.0, 5, 0),)
    geometry = GeometryText(
        caption="Quarterly Operating Results",
        stubs=(
            "Natural Gas Basis Swaps:",
            "April - December 2026",
            "January - December 2027",
            "January - December 2028",
            "Total",
        ),
        headers=("Average Fixed Price", "Volume"),
    )
    result = compete(geometry, terms)
    assert result.claims == ()


def test_reach_admits_period_listing_in_competition():
    terms = (SignatureTerm("derivatives_hedging", "stub", "swaps", 1.0, 5, 0),)
    geometry = GeometryText(
        stubs=(
            "Natural Gas Basis Swaps:",
            "April - December 2026",
            "January - December 2027",
            "January - December 2028",
            "Total",
        ),
        headers=("Notional Amount", "Fair Value"),
    )
    result = compete(geometry, terms)
    assert result.claims == ("derivatives_hedging",)
    group = result.groups[0]
    assert group.state == "reach" and group.score >= 5.0


def test_period_label_year_is_range_ruled():
    """Delta pin: the homed year recognizer spans 1900-9999; the
    deleted private copy accepted any 4-digit token as a year."""
    assert _is_period_label("January - December 2027")
    assert _is_period_label("January 2027")
    assert not _is_period_label("January 1899")
    assert not _is_period_label("January 1234")


def test_text_channels_default_empty():
    text = DerivativesText.from_geometry(GeometryText(stubs=("Swaps",)))
    verdict = evaluate_derivatives_evidence(text, SPEC)
    assert verdict.admitted and verdict.evidence_class == "U"


_UHAUL_PROSE = (
    "Recognition of Investment Income. Interest income from bonds and"
    " mortgage notes is recognized when earned. Dividends on common and"
    " preferred stocks are recognized on the ex-dividend dates. Realized"
    " gains and losses on the sale or exchange of investments are"
    " recognized at the trade date.\n"
    "Derivative Financial Instruments\n"
    "Our objective for holding derivative financial instruments is to"
    " manage interest rate risk exposure primarily through entering"
    " interest rate swap agreements and call options. We do not enter"
    " into these instruments for trading purposes. Counterparties to"
    " the interest rate swap agreements are major financial"
    " institutions. Derivatives are recognized at fair value on the"
    " balance sheet and are classified as prepaid expenses (asset) or"
    " accrued expenses (liability). Derivatives that are not designated"
    " as cash flow hedges for accounting purposes must be adjusted to"
    " fair value through income. If the derivative qualifies and is"
    " designated as a cash flow hedge, changes in its fair value will"
    " be recorded in accumulated other comprehensive income (loss) until"
    " the hedged item is recognized in earnings. See Note 11,"
    " Derivatives, of the Notes to Consolidated Financial Statements.\n"
    "Inventories and parts, net\n"
    "Inventories and parts, net were as follows:"
)


def _context(rows, prose_before, caption_stack=()):
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
    return TableContext(
        geometry=geometry,
        prose_before=prose_before,
        caption_stack=caption_stack,
    )


def test_uhaul_inventories_table_refused_through_the_production_seam():
    rows = (
        ("", "March 31,", "", ""),
        ("", "2021", "", "2020"),
        ("Truck and trailer parts and accessories", "$", "95,976", "$"),
        ("Hitches and towing components", "", "19,972", ""),
        ("Moving supplies and propane", "", "12,877", ""),
        ("Subtotal", "", "128,825", ""),
        ("Total", "$", "105,577", "$"),
    )
    table = structure_table(_context(rows, _UHAUL_PROSE, ("March 31,",)))
    geometry = geometry_text_from_table(table)
    assert geometry.leadin == (
        "Inventories and parts, net\nInventories and parts, net were as follows:"
    )
    assert "derivative" not in geometry.lead_title.lower()
    assert not _verdict(geometry).admitted
    assert "derivatives_hedging" not in compete(geometry).claims


def test_framing_prose_true_still_admits_through_the_production_seam():
    prose = (
        "Non-designated Hedging Strategy\n"
        "The Company enters into forward exchange contracts to hedge"
        " certain nonfunctional currency monetary accounts. The purpose"
        " of the Company’s foreign currency hedging activities is to"
        " protect the Company from risk that the eventual U.S. dollar"
        " equivalent cash flows from the nonfunctional currency monetary"
        " accounts will be adversely affected by changes in the exchange"
        " rates.\n"
        "For derivative instruments that are non-designated, the gain"
        " or loss on the derivative instrument subject to the hedged"
        " risk (i.e., nonfunctional currency monetary accounts) is"
        " recognized in other income (expense), net in current"
        " earnings.\n"
        "The Company had the following outstanding foreign currency"
        " forward contracts that hedge the fair value of nonfunctional"
        " currency monetary accounts (in millions):"
    )
    rows = (
        ("Currency Denomination", "", "", ""),
        ("Foreign Currency", "December 31, 2014", "", "December 31, 2013"),
        ("Norwegian Krone", "NOK", "4,052", "NOK", "3,257"),
        ("U.S. Dollar", "$", "1,092", "$", "715"),
        ("Euro", "EUR", "401", "EUR", "310"),
        ("Danish Krone", "DKK", "322", "DKK", "177"),
    )
    table = structure_table(_context(rows, prose, ("Currency Denomination",)))
    geometry = geometry_text_from_table(table)
    assert geometry.leadin == prose
    assert _verdict(geometry).admitted
