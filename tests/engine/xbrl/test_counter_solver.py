"""Unit tests for CounterSolver and Epistemic Quarantine."""

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.counter_solver import CounterSolver
from edgar_sec.engine.xbrl.domain import load_domain_taxonomy
from edgar_sec.engine.xbrl.evidence import EvidenceKnowledgeBase, UnificationRule
from edgar_sec.engine.xbrl.models import CalculationArc, XbrlFact
from edgar_sec.engine.xbrl.solver import XbrlConstraintSolver


def test_conservation_of_facts_quarantine() -> None:
    """Verify that unconsumed facts are strictly partitioned into quarantine."""
    tax = load_domain_taxonomy()
    kb = EvidenceKnowledgeBase(taxonomy=tax)
    primary = XbrlConstraintSolver(kb)
    counter = CounterSolver(primary)
    acc = AccessionNumber("0000950170-24-087843")

    facts = [
        XbrlFact(acc, "us-gaap:Revenues", 100.0),
        XbrlFact(acc, "us-gaap:CostOfGoodsAndServicesSold", 40.0),
        XbrlFact(acc, "msft:CloudInfrastructureRestructuringCharge", 25.0),
        XbrlFact(acc, "custom:NonMonetaryNotice", None),
    ]

    outcome = counter.audit_filing(facts, target_goals=["GrossProfit"])
    # Conservation of Facts Law
    total_partition = (
        len(outcome.solved_facts)
        + len(outcome.rejected_facts)
        + len(outcome.quarantined_facts)
    )
    assert total_partition == len(facts)
    assert len(outcome.quarantined_facts) == 1
    assert (
        outcome.quarantined_facts[0].fact.concept_qname
        == "msft:CloudInfrastructureRestructuringCharge"
    )
    assert len(outcome.rejected_facts) == 1


def test_zero_residual_subtotal_audit() -> None:
    """Verify discovery of shadowed leaf matching breakdown discrepancy."""
    tax = load_domain_taxonomy()
    kb = EvidenceKnowledgeBase(taxonomy=tax)
    primary = XbrlConstraintSolver(kb)
    counter = CounterSolver(primary)
    acc = AccessionNumber("0000950170-24-087843")

    facts = [
        XbrlFact(acc, "us-gaap:GrossProfit", 55.0),
        XbrlFact(acc, "msft:DirectRevenue", 100.0),
        XbrlFact(acc, "msft:DirectCost", 40.0),
        XbrlFact(acc, "msft:ShadowPackagingFee", 5.0),
    ]
    calc_arcs = [
        CalculationArc("us-gaap:GrossProfit", "msft:DirectRevenue", weight=1.0),
        CalculationArc("us-gaap:GrossProfit", "msft:DirectCost", weight=-1.0),
    ]

    outcome = counter.audit_filing(
        facts, target_goals=["us-gaap:GrossProfit"], calculation_arcs=calc_arcs
    )
    assert len(outcome.hypotheses) > 0
    shadow = next(
        h for h in outcome.hypotheses if h.concept_qname == "msft:ShadowPackagingFee"
    )
    assert shadow.hypothesis_type == "SHADOW_LEAF"
    assert shadow.residual_delta < 1e-4


def test_cross_firm_rule_weight_discounting() -> None:
    """Verify intra-firm full weight vs cross-firm prior discounting."""
    rule = UnificationRule(
        rule_id="R_MSFT_CLOUD",
        target_node="us-gaap:Revenues",
        concept_qname="msft:CloudServicesRevenue",
        weight=1.0,
        scope=("MSFT", "Technology", "*"),
    )

    w_self = CounterSolver.evaluate_rule_weight(rule, firm="MSFT", sector="Technology")
    assert w_self == 1.0

    w_cross = CounterSolver.evaluate_rule_weight(
        rule, firm="GOOGL", sector="Technology"
    )
    assert w_cross == 0.5

    w_mismatch = CounterSolver.evaluate_rule_weight(rule, firm="XOM", sector="Energy")
    assert w_mismatch == 0.0
