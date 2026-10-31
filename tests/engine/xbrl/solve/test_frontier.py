"""Tests for solver-facing frontier and antichain bridges."""

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.schema.models import CalculationArc, XbrlFact
from edgar_sec.engine.xbrl.solve.antichain import AntiChainValidator
from edgar_sec.engine.xbrl.solve.frontier import (
    resolve_query_frontier,
    verify_non_double_counting,
)
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy


def test_frontier_bridge_detects_nested_calculation_components() -> None:
    taxonomy = load_domain_taxonomy()
    validator = AntiChainValidator()
    arcs = (
        CalculationArc("us-gaap:Assets", "us-gaap:AssetsCurrent", 1.0),
        CalculationArc(
            "us-gaap:Assets", "us-gaap:CashAndCashEquivalentsAtCarryingValue", 1.0
        ),
        CalculationArc(
            "us-gaap:AssetsCurrent",
            "us-gaap:CashAndCashEquivalentsAtCarryingValue",
            1.0,
        ),
    )

    outcome = verify_non_double_counting(
        validator,
        taxonomy,
        ("us-gaap:AssetsCurrent", "us-gaap:CashAndCashEquivalentsAtCarryingValue"),
        arcs,
    )
    assert not outcome.is_valid
    assert outcome.violations


def test_frontier_bridge_returns_ancestor_and_sibling_relations() -> None:
    taxonomy = load_domain_taxonomy()
    validator = AntiChainValidator()
    accession = AccessionNumber("0000950170-24-087843")
    facts = (
        XbrlFact(accession, "us-gaap:NetIncomeLoss", 88.0),
        XbrlFact(accession, "us-gaap:OperatingIncomeLoss", 109.0),
        XbrlFact(accession, "us-gaap:NonoperatingIncomeExpense", 2.0),
    )
    arcs = (
        CalculationArc("us-gaap:NetIncomeLoss", "us-gaap:OperatingIncomeLoss", 1.0),
        CalculationArc(
            "us-gaap:NetIncomeLoss", "us-gaap:NonoperatingIncomeExpense", 1.0
        ),
    )

    frontier = resolve_query_frontier(validator, taxonomy, "Income", facts, arcs)
    assert len(frontier.candidates) == 3
    assert len(frontier.pairwise_relations) == 3
