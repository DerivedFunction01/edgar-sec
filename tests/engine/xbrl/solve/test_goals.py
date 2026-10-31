"""Unit tests verifying GoalSpec and GoalPack evaluation contracts."""

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.solve.goals import GoalFixture, GoalPack, GoalSpec
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.solve.solver import XbrlConstraintSolver


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
        expected_basis="DERIVED_EXACT",
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
    # Phase 0 re-adjudication: the ASC-606 atom now subsumes the bare revenue
    # atom, so the reported fact resolves by exact derivation, not identity.
    assert aggregate.basis == "DERIVED_EXACT"
    assert aggregate.value == 391035.0
    assert aggregate.entity == "AAPL"


def _duration_fact(value: float, start: str, end: str) -> XbrlFact:
    return XbrlFact(
        accession=AccessionNumber("0000320193-26-000020"),
        concept_qname="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        value=value,
        unit="USD",
        period_type="duration",
        start_date=start,
        end_date=end,
    )


def test_goal_coordinates_match_by_length_class() -> None:
    """Verify QUARTER and YTD_3Q specs each match only their own span."""
    qtd = _duration_fact(109417.0, "2026-03-29", "2026-06-27")
    ytd = _duration_fact(364357.0, "2025-09-28", "2026-06-27")
    quarter_pack = GoalPack(
        spec=GoalSpec(
            goal_id="GOAL_QTD_REVENUE",
            target_measure="Revenues",
            time_class="QUARTER",
            unit_class="USD",
        )
    )
    ytd_pack = GoalPack(
        spec=GoalSpec(
            goal_id="GOAL_YTD_REVENUE",
            target_measure="Revenues",
            time_class="YTD_3Q",
            unit_class="USD",
        )
    )
    assert quarter_pack._matches_coordinates(qtd)
    assert not quarter_pack._matches_coordinates(ytd)
    assert ytd_pack._matches_coordinates(ytd)
    assert not ytd_pack._matches_coordinates(qtd)
