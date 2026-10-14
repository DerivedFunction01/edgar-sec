"""Unit tests verifying GoalSpec and GoalPack evaluation contracts."""

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.domain import load_domain_taxonomy
from edgar_sec.engine.xbrl.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.goals import GoalFixture, GoalPack, GoalSpec
from edgar_sec.engine.xbrl.models import XbrlFact
from edgar_sec.engine.xbrl.solver import XbrlConstraintSolver


def test_goal_pack_evaluate_revenue() -> None:
    """Verify GoalPack evaluation against normalized facts."""
    tax = load_domain_taxonomy()
    solver = XbrlConstraintSolver(EvidenceKnowledgeBase(taxonomy=tax))
    spec = GoalSpec(
        goal_id="GOAL_ANNUAL_REVENUE",
        target_measure="Revenues",
        time_class="ANNUAL",
        unit_class="USD",
    )
    fixture = GoalFixture(
        entity="0000320193",
        accession="0000320193-24-000106",
        expected_basis="REPORTED",
        expected_value=391035.0,
    )
    pack = GoalPack(spec=spec, fixtures=(fixture,))

    acc = AccessionNumber("0000320193-24-000106")
    facts = [
        XbrlFact(
            accession=acc,
            concept_qname="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            value=391035.0,
            unit="USD",
            period_type="duration",
            start_date="2023-10-01",
            end_date="2024-09-30",
        )
    ]

    aggregate = pack.evaluate(solver, facts, entity="AAPL", period="FY2024")
    assert aggregate.basis == "REPORTED"
    assert aggregate.value == 391035.0
    assert aggregate.entity == "AAPL"
