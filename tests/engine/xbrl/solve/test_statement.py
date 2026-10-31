"""Tests proving Layer 3 algebraic statement graphs, rollups, and YoY math."""

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.schema.models import CalculationArc, XbrlFact
from edgar_sec.engine.xbrl.solve.statement import (
    IncomeStatementGraph,
    build_statement_graph,
)
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.engine.xbrl.solve.conftest import (
    load_seed_calculation_arcs,
    load_seed_facts,
    seed_folder,
)


def test_statement_graph_construction_and_rollup() -> None:
    """Verify statement graph node hierarchy, parent rollup, and chain."""
    facts = load_seed_facts("msft_2024_10k")
    arcs = load_seed_calculation_arcs("msft_2024_10k")
    tax = load_domain_taxonomy()

    graph = build_statement_graph(
        root_concept="us-gaap:GrossProfit",
        statement_type="Income Statement",
        facts=facts,
        arcs=arcs,
        taxonomy=tax,
        period_type="duration",
        graph_cls=IncomeStatementGraph,
    )

    assert graph.root_qname == "us-gaap:GrossProfit"
    assert graph.root is not None
    assert graph.root.value == 171008000000.0

    children = graph.children("us-gaap:GrossProfit")
    assert len(children) == 2
    child_qnames = {c.concept_qname for c in children}
    assert "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax" in child_qnames
    assert "us-gaap:CostOfGoodsAndServicesSold" in child_qnames

    chain = graph.chain("us-gaap:CostOfGoodsAndServicesSold")
    assert len(chain) == 2
    assert chain[0].concept_qname == "us-gaap:CostOfGoodsAndServicesSold"
    assert chain[1].concept_qname == "us-gaap:GrossProfit"

    proof = graph.verify_antichain()
    assert proof.is_valid is True
    assert proof.computed_sum == 171008000000.0


def test_statement_graph_multi_year_and_filter() -> None:
    """Verify multi-year values, YoY delta computation, and year filtering."""
    facts = load_seed_facts("msft_2024_10k")
    arcs = load_seed_calculation_arcs("msft_2024_10k")
    tax = load_domain_taxonomy()

    graph = build_statement_graph(
        root_concept="us-gaap:GrossProfit",
        statement_type="Income Statement",
        facts=facts,
        arcs=arcs,
        taxonomy=tax,
        period_type="duration",
    )

    assert "2024" in graph.years
    assert "2023" in graph.years
    assert "2022" in graph.years

    root_node = graph.root
    assert root_node is not None
    assert root_node.values.get("2024") == 171008000000.0
    assert root_node.values.get("2023") == 146052000000.0
    assert root_node.yoy_change == (171008000000.0 - 146052000000.0)
    assert root_node.yoy_pct is not None
    assert round(root_node.yoy_pct, 4) == round(24956000000.0 / 146052000000.0, 4)

    filtered = graph.filter_year(2023)
    assert filtered.years == ("2023",)
    assert filtered.root is not None
    assert filtered.root.value == 146052000000.0


def test_multi_firm_statement_graphs_across_8_fixtures() -> None:
    """Prove statement graph build and anti-chain validation across all 8 fixtures."""
    firms = ("msft", "aapl", "jnj", "f", "jpm", "apd", "amzn", "dis")
    tax = load_domain_taxonomy()

    roots = {
        "msft": "us-gaap:GrossProfit",
        "aapl": "us-gaap:GrossProfit",
        "jnj": "us-gaap:GrossProfit",
        "f": "us-gaap:OperatingIncomeLoss",
        "jpm": "jpm:NetIncomeApplicableToCommonEquity",
        "apd": "us-gaap:OperatingIncomeLoss",
        "amzn": "us-gaap:OperatingIncomeLoss",
        "dis": "us-gaap:NetIncomeLoss",
    }

    for firm in firms:
        facts = load_seed_facts(seed_folder(firm))
        arcs = load_seed_calculation_arcs(seed_folder(firm))
        root = roots[firm]

        graph = build_statement_graph(
            root_concept=root,
            statement_type="Income Statement",
            facts=facts,
            arcs=arcs,
            taxonomy=tax,
            period_type="duration",
        )

        assert graph.root is not None
        assert graph.root.value is not None
        assert len(graph.years) >= 2
        proof = graph.verify_antichain()
        assert proof.is_valid is True


def test_instant_graph_tolerates_facts_without_instant_date() -> None:
    """Verify an instant graph tolerates duration facts instead of crashing."""
    accession = AccessionNumber.from_any("0000063908-25-000012")
    facts = (
        XbrlFact(
            accession=accession,
            concept_qname="us-gaap:Assets",
            value=100.0,
            period_type="instant",
            instant_date="2024-12-31",
            dimensions={},
        ),
        XbrlFact(
            accession=accession,
            concept_qname="us-gaap:CashAndCashEquivalentsAtCarryingValue",
            value=60.0,
            period_type="instant",
            instant_date="2024-12-31",
            dimensions={},
        ),
        XbrlFact(
            accession=accession,
            concept_qname="us-gaap:CashAndCashEquivalentsAtCarryingValue",
            value=999.0,
            period_type="duration",
            start_date="2024-01-01",
            end_date="2024-12-31",
            dimensions={},
        ),
    )
    arcs = (
        CalculationArc(
            parent_qname="us-gaap:Assets",
            child_qname="us-gaap:CashAndCashEquivalentsAtCarryingValue",
            weight=1.0,
            order=1.0,
            role_uri="",
        ),
    )
    graph = build_statement_graph(
        root_concept="us-gaap:Assets",
        statement_type="Balance Sheet",
        facts=facts,
        arcs=arcs,
        taxonomy=load_domain_taxonomy(),
        period_type="instant",
    )
    cash = graph.nodes["us-gaap:CashAndCashEquivalentsAtCarryingValue"]
    assert cash.value == 60.0
    assert cash.values == {"2024": 60.0}


def test_graph_year_value_prefers_annual_span_and_finest_decimals() -> None:
    """Verify a year value is the annual fact, not a quarterly or rounded one."""
    accession = AccessionNumber.from_any("0000063908-25-000012")
    duration_facts = (
        XbrlFact(
            accession=accession,
            concept_qname="us-gaap:NetIncomeLoss",
            value=100.0,
            period_type="duration",
            start_date="2024-01-01",
            end_date="2024-12-31",
            dimensions={},
        ),
        XbrlFact(
            accession=accession,
            concept_qname="us-gaap:NetIncomeLoss",
            value=30.0,
            period_type="duration",
            start_date="2024-10-01",
            end_date="2024-12-31",
            dimensions={},
        ),
    )
    graph = build_statement_graph(
        root_concept="us-gaap:NetIncomeLoss",
        statement_type="Income Statement",
        facts=duration_facts,
        arcs=(),
        taxonomy=load_domain_taxonomy(),
        period_type="duration",
    )
    node = graph.nodes["us-gaap:NetIncomeLoss"]
    assert node.value == 100.0
    assert node.values == {"2024": 100.0}

    instant_facts = (
        XbrlFact(
            accession=accession,
            concept_qname="us-gaap:Assets",
            value=987.0,
            period_type="instant",
            instant_date="2024-12-31",
            decimals=-6,
            dimensions={},
        ),
        XbrlFact(
            accession=accession,
            concept_qname="us-gaap:Assets",
            value=990.0,
            period_type="instant",
            instant_date="2024-12-31",
            decimals=-8,
            dimensions={},
        ),
    )
    graph = build_statement_graph(
        root_concept="us-gaap:Assets",
        statement_type="Balance Sheet",
        facts=instant_facts,
        arcs=(),
        taxonomy=load_domain_taxonomy(),
        period_type="instant",
    )
    assert graph.nodes["us-gaap:Assets"].value == 987.0
