"""Derivatives-evidence gate: registry data, specimen shapes, seat."""

from __future__ import annotations

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
from edgar_sec.engine.tables.extraction.derivatives_evidence import (
    DerivativesText,
    derivatives_evidence_for_geometry,
    evaluate_derivatives_evidence,
    evaluate_form_test_derivatives,
)
from edgar_sec.engine.tables.extraction.form_test_specs import (
    DERIVATIVES_EVIDENCE_SPECS,
    DERIVATIVES_EVIDENCE_SPECS_BY_TEST_ID,
    FORM_TEST_SPECS,
)
from edgar_sec.engine.tables.extraction.profiles import (
    TEST_DERIVATIVES_EVIDENCE,
    profile_for,
)
from edgar_sec.engine.tables.extraction.signature_profiles import SignatureTerm
from edgar_sec.engine.tables.extraction.typed_rows import structure_table

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


def test_text_channels_default_empty():
    text = DerivativesText.from_geometry(GeometryText(stubs=("Swaps",)))
    verdict = evaluate_derivatives_evidence(text, SPEC)
    assert verdict.admitted and verdict.evidence_class == "U"
