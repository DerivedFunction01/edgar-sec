"""CounterSolver quarantine conservation: the fact partition law."""

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.solve.evaluation.counter_solver import CounterSolver
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.solve.core.solver import XbrlConstraintSolver


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
