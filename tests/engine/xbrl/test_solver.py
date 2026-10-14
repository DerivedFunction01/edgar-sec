"""Unit tests for XBRL constraint solver and multi-hop derivation."""

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.domain import load_domain_taxonomy
from edgar_sec.engine.xbrl.evidence import (
    EvidenceKnowledgeBase,
    UnificationRule,
)
from edgar_sec.engine.xbrl.models import (
    CalculationArc,
    XbrlFact,
)
from edgar_sec.engine.xbrl.solver import XbrlConstraintSolver


def test_solve_placements_via_calc_arc_and_kb() -> None:
    """Verify solver placement determination via calc arcs and KB backoff."""
    tax = load_domain_taxonomy()
    kb = EvidenceKnowledgeBase(taxonomy=tax)
    kb.add_rule(
        UnificationRule(
            "R1",
            "us-gaap:GrossProfit",
            "msft:CustomDirectCost",
            weight=-1.0,
            scope=("*", "*", "*"),
        )
    )

    solver = XbrlConstraintSolver(kb)
    acc = AccessionNumber("0000950170-24-087843")
    facts = [
        XbrlFact(acc, "msft:DirectRevenue", 100.0),
        XbrlFact(acc, "msft:CustomDirectCost", 30.0),
        XbrlFact(acc, "msft:UnknownKPI", 5.0, unit="pure"),
    ]
    calc_arcs = [
        CalculationArc("us-gaap:GrossProfit", "msft:DirectRevenue", weight=1.0),
    ]

    preds = solver.solve_placements(facts, calc_arcs)
    assert len(preds) == 3

    p0 = next(p for p in preds if p.concept_qname == "msft:DirectRevenue")
    assert p0.predicted_parent == "us-gaap:GrossProfit"
    assert p0.predicted_weight == 1.0

    p1 = next(p for p in preds if p.concept_qname == "msft:CustomDirectCost")
    assert p1.predicted_parent == "us-gaap:GrossProfit"
    assert p1.predicted_weight == -1.0

    p2 = next(p for p in preds if p.concept_qname == "msft:UnknownKPI")
    assert p2.is_abstained


def test_evaluate_goal_derived_multi_hop() -> None:
    """Verify multi-hop derivation of GrossProfit from Revenue and COGS."""
    tax = load_domain_taxonomy()
    kb = EvidenceKnowledgeBase(taxonomy=tax)
    solver = XbrlConstraintSolver(kb)

    acc = AccessionNumber("0000950170-24-087843")
    facts = [
        XbrlFact(
            acc,
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            245122.0,
        ),
        XbrlFact(acc, "us-gaap:CostOfGoodsAndServicesSold", 75827.0),
    ]
    calc_arcs = [
        CalculationArc(
            "us-gaap:GrossProfit",
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            weight=1.0,
        ),
        CalculationArc(
            "us-gaap:GrossProfit",
            "us-gaap:CostOfGoodsAndServicesSold",
            weight=-1.0,
        ),
    ]

    goal = solver.evaluate_goal("us-gaap:GrossProfit", facts, calc_arcs)
    assert goal.computed_value == 169295.0
    assert goal.resolution_tier == "DERIVED_MULTI_HOP"
    assert not goal.is_direct
