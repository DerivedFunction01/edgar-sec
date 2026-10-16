from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.schema.models import CalculationArc, XbrlFact
from edgar_sec.engine.xbrl.solve.placement import solve_placements
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy


def test_calculation_arc_placement_is_used_first() -> None:
    fact = XbrlFact(AccessionNumber("0000950170-24-087843"), "custom:Revenue", 10.0)
    arc = CalculationArc("us-gaap:GrossProfit", "custom:Revenue", 1.0)

    result = solve_placements(
        EvidenceKnowledgeBase(load_domain_taxonomy()), [fact], [arc]
    )

    assert result[0].predicted_parent == "us-gaap:GrossProfit"
    assert result[0].predicted_weight == 1.0
