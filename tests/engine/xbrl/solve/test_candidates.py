from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.schema.models import CalculationArc, XbrlFact
from edgar_sec.engine.xbrl.solve.candidates import classify_candidate_facts


def test_candidate_classification_accepts_target_and_arc_child() -> None:
    accession = AccessionNumber("0000950170-24-087843")
    facts = [
        XbrlFact(accession, "us-gaap:Profit", 7.0),
        XbrlFact(accession, "us-gaap:Revenue", 10.0),
        XbrlFact(accession, "custom:Unknown", 2.0),
    ]
    arcs = [CalculationArc("us-gaap:Profit", "us-gaap:Revenue", 1.0)]

    result = classify_candidate_facts("us-gaap:Profit", facts, arcs)

    assert [verdict.decision for verdict in result] == ["ACCEPT", "ACCEPT", "UNKNOWN"]
