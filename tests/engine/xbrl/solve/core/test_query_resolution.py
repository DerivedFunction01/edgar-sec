"""Tests for scoped concept-query resolution and status."""

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.normalize.decomposer import decompose_concept
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.solve.core.query import (
    FinancialQuery,
    QueryMode,
    QueryStatus,
)
from edgar_sec.engine.xbrl.solve.core.scoping import FactScope
from edgar_sec.engine.xbrl.solve.evaluation.verification import DoubleCountVerifier
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.support.corpus import bundle_text
from tests.engine.xbrl.solve.conftest import load_seed_calculation_arcs, load_seed_facts
from .query_fixtures import (
    _duration_usd_fact,
    _instant_usd_fact,
    _query_engine,
    _table_declarations,
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


def test_specific_customer_revenue_query_skips_the_contract_liability_burn_down() -> (
    None
):
    """F5: the specific query answers the filed customer-revenue total;
    the burn-down concept answers only its own exact-qname query.
    """
    facts = load_seed_facts("aapl_2024_10k")
    engine = _query_engine()
    scope = FactScope(
        accession="0000320193-24-000123",
        start_date="2023-10-01",
        end_date="2024-09-28",
        unit="USD",
    )

    specific = engine.execute(
        FinancialQuery("revenue from contract with customer", scope), facts
    )
    assert specific.status == QueryStatus.REPORTED
    assert specific.candidate_qnames == (
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
    )
    assert specific.value == 391_035_000_000.0

    exact = engine.execute(
        FinancialQuery("us-gaap:ContractWithCustomerLiabilityRevenueRecognized", scope),
        facts,
    )
    assert exact.status == QueryStatus.REPORTED
    assert exact.value == 7_700_000_000.0

    bare = engine.execute(FinancialQuery("revenue", scope), facts)
    assert (
        "us-gaap:ContractWithCustomerLiabilityRevenueRecognized"
        not in bare.candidate_qnames
    )


def test_percent_typed_extension_never_answers_a_monetary_query() -> None:
    """HON shape: a percent-typed extension is barred from the revenue pool;
    its own exact-qname query still answers it.
    """
    from edgar_sec.engine.xbrl.schema.models import ConceptDeclaration

    qname = "hon:RevenueFromContractWithCustomerPercentage"
    declarations = {
        qname: ConceptDeclaration(
            concept_qname=qname,
            name="RevenueFromContractWithCustomerPercentage",
            item_type="dtr-types1:percentItemType",
        )
    }
    engine = _query_engine(declarations=declarations)
    facts = (
        _duration_usd_fact(qname, 0.42, unit="pure"),
        _duration_usd_fact(
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 245_122.0
        ),
    )
    scope = FactScope(
        accession="0000950170-24-087843",
        start_date="2023-07-01",
        end_date="2024-06-30",
    )

    specific = engine.execute(
        FinancialQuery("revenue from contract with customer", scope), facts
    )
    assert specific.status == QueryStatus.REPORTED
    assert specific.candidate_qnames == (
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
    )
    assert specific.value == 245_122.0
    assert all(item.qname != qname for item in specific.equivalents)

    exact = engine.execute(
        FinancialQuery(
            qname,
            FactScope(
                accession="0000950170-24-087843",
                start_date="2023-07-01",
                end_date="2024-06-30",
                unit="pure",
            ),
        ),
        facts,
    )
    assert exact.status == QueryStatus.REPORTED
    assert exact.candidate_qnames == (qname,)
    assert exact.value == 0.42


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

    text = bundle_text("aapl_2024_10k")
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


def test_query_alias_specs_match_retired_string_decompositions() -> None:
    """Pin declared alias specs to the decompositions of the concept
    names they replaced."""
    tax = load_domain_taxonomy()
    retired = {
        "aoci": (
            "us-gaap:AccumulatedOtherComprehensiveIncomeLossNetOfTax",
            "us-gaap:OtherComprehensiveIncomeLossNetOfTaxPortionAttributableToParent",
        ),
        "capex": (
            "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment",
            "us-gaap:PaymentsToAcquireProductiveAssets",
        ),
        "cfo": ("us-gaap:NetCashProvidedByUsedInOperatingActivities",),
        "eps": (
            "us-gaap:EarningsPerShareBasic",
            "us-gaap:EarningsPerShareDiluted",
        ),
    }
    for alias, qnames in retired.items():
        expected = {decompose_concept(q, tax.token_lexicon)[0] for q in qnames}
        assert set(tax.query_alias_atoms(alias)) == expected


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


def test_xva_fact_no_longer_ambiguates_the_derivative_assets_query() -> None:
    """BAC shape: the XVA name is a NEAR neighbour, not an exact-pool rival.
    Re-adjudicated pin: the dissolved false EXACT used to force AMBIGUOUS.
    """
    xva = "bac:DerivativeFundingRiskValuationAdjustmentDerivativeAssets"
    facts = (
        _instant_usd_fact(xva, 66_000_000.0, None),
        _instant_usd_fact("us-gaap:DerivativeAssets", 180_000_000.0, None),
    )
    scope = FactScope(
        accession="0000950170-24-087843",
        instant_date="2024-06-30",
        unit="USD",
    )
    result = _query_engine().execute(FinancialQuery("DerivativeAssets", scope), facts)
    assert result.status == QueryStatus.REPORTED
    assert result.value == 180_000_000.0
    assert result.candidate_qnames == ("us-gaap:DerivativeAssets",)
    assert result.tier == "exact"
    by_qname = {item.qname: item for item in result.equivalents}
    assert by_qname["us-gaap:DerivativeAssets"].tier == "exact"
    assert by_qname["us-gaap:DerivativeAssets"].rule == "equality"
    assert by_qname[xva].tier == "near"
    assert by_qname[xva].rule == "single_modifier_difference"
    assert by_qname[xva].direction == "specialization"


def test_concept_query_keeps_free_text_parsing_out_of_scope() -> None:
    engine = _query_engine()
    assert engine.parse_terms("NetIncome") == ("Net", "Income")
    assert engine.parse_terms("Net Income") == ("Net", "Income")
