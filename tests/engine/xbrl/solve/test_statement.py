"""Tests proving Layer 3 algebraic statement graphs, rollups, and YoY math."""

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.solve.statement import (
    IncomeStatementGraph,
    build_statement_graph,
)
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.engine.xbrl.solve.conftest import load_seed_calculation_arcs, load_seed_facts


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
        facts = load_seed_facts(f"{firm}_2024_10k")
        arcs = load_seed_calculation_arcs(f"{firm}_2024_10k")
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
