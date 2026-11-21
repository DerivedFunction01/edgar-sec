"""Tests proving anti-chain non-double-counting and query frontier relations."""

from edgar_sec.engine.xbrl.solve.antichain import (
    AntiChainValidator,
    CandidateRelation,
)


def test_antichain_valid_partition() -> None:
    """Prove valid anti-chain components pass without double-counting violations."""
    validator = AntiChainValidator()
    arcs = [
        ("us-gaap:GrossProfit", "us-gaap:Revenue", 1.0),
        ("us-gaap:GrossProfit", "us-gaap:CostOfRevenue", -1.0),
    ]
    values = {
        "us-gaap:GrossProfit": 171008.0,
        "us-gaap:Revenue": 245122.0,
        "us-gaap:CostOfRevenue": 74114.0,
    }
    weights = {"us-gaap:Revenue": 1.0, "us-gaap:CostOfRevenue": -1.0}

    outcome = validator.verify_non_double_counting(
        selected_concepts=["us-gaap:Revenue", "us-gaap:CostOfRevenue"],
        calculation_arcs=arcs,
        target_concept="us-gaap:GrossProfit",
        concept_values=values,
        concept_weights=weights,
    )
    assert outcome.is_valid is True
    assert outcome.discrepancy == 0.0
    assert len(outcome.violations) == 0


def test_antichain_refusal_on_ancestor_descendant() -> None:
    """Prove engine refuses aggregation when parent and child are both included."""
    validator = AntiChainValidator()
    arcs = [
        ("us-gaap:NetIncome", "us-gaap:OperatingIncome", 1.0),
        ("us-gaap:OperatingIncome", "us-gaap:GrossProfit", 1.0),
        ("us-gaap:GrossProfit", "us-gaap:Revenue", 1.0),
    ]

    outcome = validator.verify_non_double_counting(
        selected_concepts=["us-gaap:OperatingIncome", "us-gaap:Revenue"],
        calculation_arcs=arcs,
    )
    assert outcome.is_valid is False
    assert len(outcome.violations) == 1
    assert "Double-counting" in outcome.violations[0]
    assert "OperatingIncome" in outcome.violations[0]
    assert "Revenue" in outcome.violations[0]


def test_resolve_query_frontier_overlap_and_disjointness() -> None:
    """Prove candidate frontier classifies ancestor overlap vs disjoint siblings."""
    validator = AntiChainValidator()
    arcs = [
        ("us-gaap:NetIncomeLoss", "us-gaap:OperatingIncomeLoss", 1.0),
        ("us-gaap:NetIncomeLoss", "us-gaap:NonoperatingIncomeExpense", 1.0),
    ]
    candidate_facts = [
        {"concept_qname": "us-gaap:NetIncomeLoss", "numeric_value": 88136.0},
        {"concept_qname": "us-gaap:OperatingIncomeLoss", "numeric_value": 109433.0},
        {"concept_qname": "us-gaap:NonoperatingIncomeExpense", "numeric_value": 2000.0},
    ]

    frontier = validator.resolve_query_frontier(
        query_concept="Income",
        candidate_facts=candidate_facts,
        calculation_arcs=arcs,
    )
    assert len(frontier.candidates) == 3

    pair_map = {
        (p.concept_a, p.concept_b): p.relation for p in frontier.pairwise_relations
    }
    assert (
        pair_map[("us-gaap:NetIncomeLoss", "us-gaap:OperatingIncomeLoss")]
        == CandidateRelation.ANCESTOR_DESCENDANT_OVERLAP
    )
    assert (
        pair_map[("us-gaap:OperatingIncomeLoss", "us-gaap:NonoperatingIncomeExpense")]
        == CandidateRelation.DISJOINT_SIBLING
    )


def test_render_ascii_tree_and_frontier() -> None:
    """Verify human-inspectable rendering for anti-chain trees and frontiers."""
    validator = AntiChainValidator()
    comps = [
        {"concept": "us-gaap:Revenue", "weight": 1.0, "value": 245122.0},
        {"concept": "us-gaap:CostOfRevenue", "weight": -1.0, "value": 74114.0},
    ]
    tree = validator.render_ascii_tree("us-gaap:GrossProfit", comps, 171008.0)
    assert "Target Root: us-gaap:GrossProfit = $171,008" in tree
    assert "[+] us-gaap:Revenue" in tree
    assert "Anti-Chain Invariant: VERIFIED" in tree
