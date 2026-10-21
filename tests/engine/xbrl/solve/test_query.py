"""Tests for scoped concept queries and graph-only reconciliation."""

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.solve.query import (
    FinancialQuery,
    FinancialQueryEngine,
    QueryMode,
    QueryStatus,
)
from edgar_sec.engine.xbrl.solve.scoping import FactScope
from edgar_sec.engine.xbrl.solve.solver import XbrlConstraintSolver
from edgar_sec.engine.xbrl.solve.verification import DoubleCountVerifier
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.support import fixture_path
from .conftest import load_seed_calculation_arcs, load_seed_facts


def _query_engine() -> FinancialQueryEngine:
    return FinancialQueryEngine(
        XbrlConstraintSolver(EvidenceKnowledgeBase(taxonomy=load_domain_taxonomy()))
    )


def test_camel_case_and_spaced_concept_terms_resolve_equivalently() -> None:
    facts = load_seed_facts("msft_2024_10k")
    engine = _query_engine()
    scope = FactScope(
        accession="0000950170-24-087843",
        start_date="2023-07-01",
        end_date="2024-06-30",
        unit="USD",
    )

    camel = engine.execute(FinancialQuery("NetIncome", scope), facts)
    spaced = engine.execute(FinancialQuery("Net Income", scope), facts)
    assert camel.status == spaced.status == QueryStatus.REPORTED
    assert (
        camel.candidate_qnames == spaced.candidate_qnames == ("us-gaap:NetIncomeLoss",)
    )
    assert camel.value == spaced.value
    assert camel.target_atom == spaced.target_atom


def test_unscoped_repeated_concept_is_ambiguous_not_iteration_ordered() -> None:
    facts = load_seed_facts("msft_2024_10k")
    engine = _query_engine()

    result = engine.execute(
        FinancialQuery(
            "us-gaap:Assets",
            FactScope(accession="0000950170-24-087843", unit="USD"),
        ),
        facts,
    )
    assert result.status == QueryStatus.AMBIGUOUS
    assert len(result.candidate_facts) > 1


def test_unknown_term_is_unavailable_with_no_candidates() -> None:
    result = _query_engine().execute(
        FinancialQuery(
            "UnrecognizedFinancialMeasure",
            FactScope(
                accession="0000950170-24-087843",
                instant_date="2024-06-30",
                unit="USD",
            ),
        ),
        load_seed_facts("msft_2024_10k"),
    )

    assert result.status == QueryStatus.UNAVAILABLE
    assert result.candidate_qnames == ()
    assert result.candidate_facts == ()
    assert result.target_atom is not None


def test_unavailable_concept_has_no_candidate_qname() -> None:
    result = _query_engine().execute(
        FinancialQuery(
            "us-gaap:ConceptNotInThisFiling",
            FactScope(
                accession="0000950170-24-087843",
                instant_date="2024-06-30",
                unit="USD",
            ),
        ),
        load_seed_facts("msft_2024_10k"),
    )

    assert result.status == QueryStatus.UNAVAILABLE
    assert result.candidate_qnames == ()
    assert result.candidate_facts == ()


def test_derivation_without_a_period_is_ambiguous() -> None:
    accession = AccessionNumber("0000950170-24-087843")
    facts = (
        XbrlFact(
            accession,
            "us-gaap:GrossProfit",
            60.0,
            unit="USD",
            period_type="duration",
            start_date="2023-07-01",
            end_date="2024-06-30",
        ),
        XbrlFact(
            accession,
            "us-gaap:Revenues",
            100.0,
            unit="USD",
            period_type="duration",
            start_date="2023-07-01",
            end_date="2024-06-30",
        ),
        XbrlFact(
            accession,
            "us-gaap:CostOfRevenue",
            40.0,
            unit="USD",
            period_type="duration",
            start_date="2023-07-01",
            end_date="2024-06-30",
        ),
    )

    result = _query_engine().execute(
        FinancialQuery(
            "us-gaap:GrossProfit",
            FactScope(accession="0000950170-24-087843", unit="USD"),
            mode=QueryMode.DERIVE_ONLY,
        ),
        facts,
    )

    assert result.status == QueryStatus.AMBIGUOUS
    assert result.candidate_qnames == ("us-gaap:GrossProfit",)
    assert len(result.candidate_facts) == 1
    assert result.reported_fact == facts[0]
    assert "period is required" in result.message


def test_scope_filters_period_unit_and_dimensions() -> None:
    facts = load_seed_facts("aapl_2024_10k")
    engine = _query_engine()
    scope = FactScope(
        accession="0000320193-24-000123",
        start_date="2023-10-01",
        end_date="2024-09-28",
        unit="USD",
    )
    total = engine.execute(
        FinancialQuery(
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", scope
        ),
        facts,
    )
    products = engine.execute(
        FinancialQuery(
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            FactScope(
                accession="0000320193-24-000123",
                start_date="2023-10-01",
                end_date="2024-09-28",
                unit="USD",
                dimensions={"srt:ProductOrServiceAxis": "us-gaap:ProductMember"},
            ),
        ),
        facts,
    )
    wrong_unit = engine.execute(
        FinancialQuery(
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            FactScope(
                accession="0000320193-24-000123",
                start_date="2023-10-01",
                end_date="2024-09-28",
                unit="shares",
            ),
        ),
        facts,
    )

    assert total.status == products.status == QueryStatus.REPORTED
    assert total.value == 391_035_000_000.0
    assert products.value == 294_866_000_000.0
    assert wrong_unit.status == QueryStatus.UNAVAILABLE
    assert wrong_unit.candidate_qnames == (
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
    )
    assert wrong_unit.candidate_facts == ()
    assert wrong_unit.value is None

    text = fixture_path("xbrl/seed/aapl_2024_10k/normalized_text.txt").read_text(
        encoding="utf-8"
    )
    product_row = DoubleCountVerifier.verify_cited_row(
        text,
        "Products",
        products.value,
        line_number=920,
        line_range=(919, 931),
        scale=1_000_000,
        expected_snippet="  Products                                             $ 294,866           $ 298,085           $ 316,199",
    )
    assert product_row.is_valid


def test_controlled_aliases_resolve_or_return_explicit_ambiguity() -> None:
    facts = load_seed_facts("aapl_2024_10k")
    engine = _query_engine()
    duration = FactScope(
        accession="0000320193-24-000123",
        start_date="2023-10-01",
        end_date="2024-09-28",
        unit="USD",
    )
    instant = FactScope(
        accession="0000320193-24-000123",
        instant_date="2024-09-28",
        unit="USD",
    )

    cash_flow = engine.execute(FinancialQuery("CFO", duration), facts)
    earnings_per_share = engine.execute(FinancialQuery("EPS", duration), facts)
    accumulated_oci = engine.execute(FinancialQuery("AOCI", instant), facts)

    assert cash_flow.status == QueryStatus.REPORTED
    assert cash_flow.candidate_qnames == (
        "us-gaap:NetCashProvidedByUsedInOperatingActivities",
    )
    assert earnings_per_share.status == QueryStatus.AMBIGUOUS
    assert set(earnings_per_share.candidate_qnames) == {
        "us-gaap:EarningsPerShareBasic",
        "us-gaap:EarningsPerShareDiluted",
    }
    assert accumulated_oci.status == QueryStatus.REPORTED
    assert accumulated_oci.candidate_qnames == (
        "us-gaap:AccumulatedOtherComprehensiveIncomeLossNetOfTax",
    )


def test_graph_only_gross_profit_reconciles_with_withheld_fact() -> None:
    facts = load_seed_facts("aapl_2024_10k")
    arcs = load_seed_calculation_arcs("aapl_2024_10k")
    engine = _query_engine()
    scope = FactScope(
        accession="0000320193-24-000123",
        start_date="2023-10-01",
        end_date="2024-09-28",
        unit="USD",
    )

    result = engine.execute(
        FinancialQuery("us-gaap:GrossProfit", scope, mode=QueryMode.VERIFY_DERIVATION),
        facts,
        arcs,
    )
    assert result.status == QueryStatus.VERIFIED
    assert result.reported_fact is not None
    assert result.reported_fact.value == 180_683_000_000.0
    assert result.aggregate is not None
    assert result.aggregate.basis == "DERIVED_EXACT"
    assert result.value == result.reported_fact.value

    text = fixture_path("xbrl/seed/aapl_2024_10k/normalized_text.txt").read_text(
        encoding="utf-8"
    )
    rows = (
        ("Total net sales", 923, 391_035_000_000.0),
        ("Total cost of sales", 929, 210_352_000_000.0),
        ("Gross margin", 931, 180_683_000_000.0),
    )
    for label, line_number, expected in rows:
        evidence = DoubleCountVerifier.verify_cited_row(
            text,
            label,
            expected,
            line_number=line_number,
            line_range=(919, 931),
            scale=1_000_000,
            expected_snippet=text.splitlines()[line_number - 1].strip(),
        )
        assert evidence.is_valid, evidence.message


def test_derivative_netting_and_notional_reconcile_to_msft_filing_rows() -> None:
    facts = load_seed_facts("msft_2024_10k")
    engine = _query_engine()
    instant = FactScope(
        accession="0000950170-24-087843",
        instant_date="2024-06-30",
        unit="USD",
    )
    fx_notional_scope = FactScope(
        accession="0000950170-24-087843",
        instant_date="2024-06-30",
        unit="USD",
        dimensions={
            "us-gaap:DerivativeInstrumentRiskAxis": "us-gaap:ForeignExchangeContractMember",
            "us-gaap:HedgingDesignationAxis": "us-gaap:DesignatedAsHedgingInstrumentMember",
            "us-gaap:PositionAxis": "us-gaap:LongMember",
        },
    )
    arcs = load_seed_calculation_arcs("msft_2024_10k")
    assets = engine.execute(
        FinancialQuery(
            "us-gaap:DerivativeAssets", instant, mode=QueryMode.VERIFY_DERIVATION
        ),
        facts,
        arcs,
    )
    liabilities = engine.execute(
        FinancialQuery(
            "us-gaap:DerivativeLiabilities",
            instant,
            mode=QueryMode.VERIFY_DERIVATION,
        ),
        facts,
        arcs,
    )
    notional = engine.execute(
        FinancialQuery("us-gaap:DerivativeNotionalAmount", fx_notional_scope), facts
    )
    gross_asset = engine.execute(
        FinancialQuery(
            "us-gaap:DerivativeAssetFairValueGrossAssetIncludingNotSubjectToMasterNettingArrangement",
            instant,
        ),
        facts,
    )

    assert assets.status == liabilities.status == QueryStatus.VERIFIED
    assert assets.value == 180_000_000.0
    assert liabilities.value == 752_000_000.0
    assert notional.status == gross_asset.status == QueryStatus.REPORTED
    assert notional.value == 1_492_000_000.0
    assert gross_asset.value == 331_000_000.0
    assert notional.value != gross_asset.value

    text = fixture_path("xbrl/seed/msft_2024_10k/normalized_text.txt").read_text(
        encoding="utf-8"
    )
    evidence = (
        ("Foreign exchange contracts purchased", 2386, notional.value, 0, 1),
        ("Gross amounts of derivatives", 2424, gross_asset.value, 0, 1),
        ("Net amounts of derivatives", 2430, assets.value, 0, 1),
        ("Net amounts of derivatives", 2430, liabilities.value, 1, -1),
    )
    for label, line_number, value, column_index, display_sign in evidence:
        row = DoubleCountVerifier.verify_cited_row(
            text,
            label,
            value,
            line_number=line_number,
            line_range=(2377, 2430),
            scale=1_000_000,
            column_index=column_index,
            expected_snippet=text.splitlines()[line_number - 1].strip(),
            display_sign=display_sign,
        )
        assert row.is_valid, row.message

    def cell(line_number: int, column_index: int) -> float:
        labels = {
            2424: "Gross amounts of derivatives",
            2425: "Gross amounts of derivatives offset in the balance sheets",
            2426: "Cash collateral received",
            2430: "Net amounts of derivatives",
        }
        value, _ = DoubleCountVerifier.extract_cited_row_value(
            text,
            labels[line_number],
            line_number=line_number,
            line_range=(2377, 2430),
            column_index=column_index,
        )
        assert value is not None
        return value

    assert cell(2424, 0) + cell(2425, 0) + cell(2426, 0) == cell(2430, 0)
    assert cell(2424, 1) + cell(2425, 1) + cell(2426, 1) == cell(2430, 1)


def test_netting_relations_resolve_composed_tags_without_source_qname_matches() -> None:
    acc = AccessionNumber("0000950170-24-087843")
    facts = (
        XbrlFact(
            acc,
            "us-gaap:DerivativeAssets",
            180_000_000.0,
            unit="USD",
            period_type="instant",
            instant_date="2024-06-30",
        ),
        XbrlFact(
            acc,
            "us-gaap:GrossFairValueDerivativeAssetNotSubjectToMasterNettingArrangement",
            331_000_000.0,
            unit="USD",
            period_type="instant",
            instant_date="2024-06-30",
        ),
        XbrlFact(
            acc,
            "us-gaap:LiabilityFairValueGrossDerivative",
            151_000_000.0,
            unit="USD",
            period_type="instant",
            instant_date="2024-06-30",
        ),
        XbrlFact(
            acc,
            "us-gaap:CashDerivativeCollateralRightToReclaim",
            0.0,
            unit="USD",
            period_type="instant",
            instant_date="2024-06-30",
        ),
    )
    scope = FactScope(
        accession="0000950170-24-087843",
        instant_date="2024-06-30",
        unit="USD",
    )
    engine = _query_engine()
    result = engine.execute(
        FinancialQuery(
            "us-gaap:DerivativeAssets", scope, mode=QueryMode.VERIFY_DERIVATION
        ),
        facts,
    )

    assert result.status == QueryStatus.VERIFIED
    assert result.aggregate is not None
    assert result.aggregate.value == 180_000_000.0
    assert all(
        fact.concept_qname
        not in {"DerivativeAssetsGross", "DerivativeAssetFairValueGrossLiability"}
        for fact in facts
    )


def test_net_of_graph_expression_derives_from_two_operand_atoms() -> None:
    acc = AccessionNumber("0000950170-24-087843")
    context = {
        "unit": "USD",
        "period_type": "duration",
        "start_date": "2023-07-01",
        "end_date": "2024-06-30",
    }
    facts = (
        XbrlFact(acc, "us-gaap:RevenuesNetOfInterestExpense", 80.0, **context),
        XbrlFact(acc, "us-gaap:Revenues", 100.0, **context),
        XbrlFact(acc, "us-gaap:InterestExpense", 20.0, **context),
    )
    query = FinancialQuery(
        "us-gaap:RevenuesNetOfInterestExpense",
        FactScope(
            accession="0000950170-24-087843",
            start_date="2023-07-01",
            end_date="2024-06-30",
            unit="USD",
        ),
        mode=QueryMode.VERIFY_DERIVATION,
    )

    result = _query_engine().execute(query, facts)
    assert result.status == QueryStatus.VERIFIED
    assert result.aggregate is not None
    assert result.aggregate.value == 80.0
    assert [
        (component.value, component.weight) for component in result.aggregate.components
    ] == [
        (100.0, 1.0),
        (20.0, -1.0),
    ]


def test_common_fundamentals_resolve_instant_duration_units_and_citations() -> None:
    facts = load_seed_facts("msft_2024_10k")
    engine = _query_engine()
    instant = FactScope(
        accession="0000950170-24-087843",
        instant_date="2024-06-30",
        unit="USD",
    )
    duration = FactScope(
        accession="0000950170-24-087843",
        start_date="2023-07-01",
        end_date="2024-06-30",
        unit="USD",
    )
    shares_duration = FactScope(
        accession="0000950170-24-087843",
        start_date="2023-07-01",
        end_date="2024-06-30",
        unit="shares",
    )
    per_share_duration = FactScope(
        accession="0000950170-24-087843",
        start_date="2023-07-01",
        end_date="2024-06-30",
        unit="USD/shares",
    )
    queries = (
        ("us-gaap:Assets", instant, "Total assets", 1683, 1_000_000, 0, 1),
        ("CFO", duration, "Net cash from operations", 1757, 1_000_000, 0, 1),
        (
            "us-gaap:LongTermDebtNoncurrent",
            instant,
            "Long-term debt",
            1700,
            1_000_000,
            0,
            1,
        ),
        (
            "us-gaap:EarningsPerShareDiluted",
            per_share_duration,
            "Diluted",
            1617,
            1,
            0,
            1,
        ),
        (
            "us-gaap:WeightedAverageNumberOfSharesOutstandingBasic",
            shares_duration,
            "Basic",
            1619,
            1_000_000,
            0,
            1,
        ),
        (
            "us-gaap:AccumulatedOtherComprehensiveIncomeLossNetOfTax",
            instant,
            "Accumulated other comprehensive loss, end of period",
            3384,
            1_000_000,
            0,
            1,
        ),
    )
    text = fixture_path("xbrl/seed/msft_2024_10k/normalized_text.txt").read_text(
        encoding="utf-8"
    )
    line_ranges = {
        1683: (1677, 1725),
        1700: (1677, 1725),
        1617: (1580, 1621),
        1619: (1580, 1621),
        1757: (1728, 1800),
        3384: (3320, 3385),
    }
    for term, scope, label, line_number, scale, column_index, display_sign in queries:
        result = engine.execute(FinancialQuery(term, scope), facts)
        assert result.status == QueryStatus.REPORTED, (term, result)
        assert result.value is not None
        evidence = DoubleCountVerifier.verify_cited_row(
            text,
            label,
            result.value,
            line_number=line_number,
            line_range=line_ranges[line_number],
            scale=scale,
            column_index=column_index,
            expected_snippet=text.splitlines()[line_number - 1].strip(),
            display_sign=display_sign,
        )
        assert evidence.is_valid, (term, evidence.message)


def test_scoping_refuses_to_mix_multiple_accessions() -> None:
    acc_a = AccessionNumber("0000950170-24-087843")
    acc_b = AccessionNumber("0000320193-24-000123")
    facts = (
        XbrlFact(
            acc_a,
            "us-gaap:NetIncomeLoss",
            10.0,
            unit="USD",
            period_type="instant",
            instant_date="2024-09-28",
        ),
        XbrlFact(
            acc_b,
            "us-gaap:NetIncomeLoss",
            20.0,
            unit="USD",
            period_type="instant",
            instant_date="2024-09-28",
        ),
    )
    engine = _query_engine()

    result = engine.execute(
        FinancialQuery(
            "us-gaap:NetIncomeLoss",
            FactScope(instant_date="2024-09-28", unit="USD"),
        ),
        facts,
    )
    assert result.status == QueryStatus.AMBIGUOUS
    assert "accession" in result.message


def test_conflicting_values_in_one_context_return_conflict() -> None:
    accession = AccessionNumber("0000950170-24-087843")
    facts = tuple(
        XbrlFact(
            accession,
            "us-gaap:NetIncomeLoss",
            value,
            unit="USD",
            period_type="duration",
            start_date="2023-07-01",
            end_date="2024-06-30",
        )
        for value in (10.0, 12.0)
    )

    result = _query_engine().execute(
        FinancialQuery(
            "us-gaap:NetIncomeLoss",
            FactScope(
                accession="0000950170-24-087843",
                start_date="2023-07-01",
                end_date="2024-06-30",
                unit="USD",
            ),
        ),
        facts,
    )

    assert result.status == QueryStatus.CONFLICT
    assert result.candidate_qnames == ("us-gaap:NetIncomeLoss",)
    assert {fact.value for fact in result.candidate_facts} == {10.0, 12.0}
    assert "Conflicting values" in result.message


def test_requested_period_selects_its_value_independent_of_fact_order() -> None:
    accession = AccessionNumber("0000950170-24-087843")
    facts = (
        XbrlFact(
            accession,
            "us-gaap:NetIncomeLoss",
            100.0,
            unit="USD",
            period_type="duration",
            start_date="2022-07-01",
            end_date="2023-06-30",
        ),
        XbrlFact(
            accession,
            "us-gaap:NetIncomeLoss",
            200.0,
            unit="USD",
            period_type="duration",
            start_date="2023-07-01",
            end_date="2024-06-30",
        ),
    )
    engine = _query_engine()

    for period, expected in (
        (("2022-07-01", "2023-06-30"), 100.0),
        (("2023-07-01", "2024-06-30"), 200.0),
    ):
        results = tuple(
            engine.execute(
                FinancialQuery(
                    "us-gaap:NetIncomeLoss",
                    FactScope(
                        accession="0000950170-24-087843",
                        start_date=period[0],
                        end_date=period[1],
                        unit="USD",
                    ),
                ),
                ordered_facts,
            )
            for ordered_facts in (facts, tuple(reversed(facts)))
        )

        assert all(result.status == QueryStatus.REPORTED for result in results)
        assert all(result.value == expected for result in results)
        assert all(result.reported_fact is not None for result in results)
        assert all(
            (result.reported_fact.start_date, result.reported_fact.end_date) == period
            for result in results
            if result.reported_fact is not None
        )


def test_derive_only_excludes_target_and_atom_equivalent_facts() -> None:
    accession = AccessionNumber("0000950170-24-087843")
    context = {
        "unit": "USD",
        "period_type": "duration",
        "start_date": "2023-07-01",
        "end_date": "2024-06-30",
    }
    facts = (
        XbrlFact(
            accession,
            "us-gaap:RevenuesNetOfInterestExpense",
            85.0,
            **context,
        ),
        XbrlFact(
            accession,
            "custom:RevenuesNetOfInterestExpense",
            900.0,
            **context,
        ),
        XbrlFact(accession, "us-gaap:Revenues", 100.0, **context),
        XbrlFact(accession, "us-gaap:InterestExpense", 20.0, **context),
    )
    query = FinancialQuery(
        "us-gaap:RevenuesNetOfInterestExpense",
        FactScope(
            accession="0000950170-24-087843",
            start_date="2023-07-01",
            end_date="2024-06-30",
            unit="USD",
        ),
        mode=QueryMode.DERIVE_ONLY,
    )

    result = _query_engine().execute(query, facts)

    assert result.status == QueryStatus.DERIVED
    assert result.candidate_qnames == ("us-gaap:RevenuesNetOfInterestExpense",)
    assert result.reported_fact is not None
    assert result.reported_fact.value == 85.0
    assert result.aggregate is not None
    assert result.aggregate.basis == "DERIVED_EXACT"
    assert result.value == 80.0
    assert [
        (component.value, component.weight) for component in result.aggregate.components
    ] == [(100.0, 1.0), (20.0, -1.0)]


def test_concept_query_keeps_free_text_parsing_out_of_scope() -> None:
    engine = _query_engine()
    assert engine.parse_terms("NetIncome") == ("Net", "Income")
    assert engine.parse_terms("Net Income") == ("Net", "Income")
