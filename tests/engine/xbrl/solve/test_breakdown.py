from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.schema.models import CalculationArc, XbrlFact
from edgar_sec.engine.xbrl.solve.breakdown import breakdown_concept
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy


def test_calculation_breakdown_applies_arc_weights() -> None:
    accession = AccessionNumber("0000950170-24-087843")
    facts = [
        XbrlFact(accession, "us-gaap:Revenue", 12.0),
        XbrlFact(accession, "us-gaap:Costs", 5.0),
    ]
    arcs = [
        CalculationArc("us-gaap:Profit", "us-gaap:Revenue", 1.0),
        CalculationArc("us-gaap:Profit", "us-gaap:Costs", -1.0),
    ]

    result = breakdown_concept(
        EvidenceKnowledgeBase(load_domain_taxonomy()), "us-gaap:Profit", facts, arcs
    )

    assert [
        (component.identifier, component.weight) for component in result.components
    ] == [
        ("us-gaap:Revenue", 1.0),
        ("us-gaap:Costs", -1.0),
    ]
