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


def test_candidate_classification_names_standard_taxonomy_facts() -> None:
    accession = AccessionNumber("0000950170-24-087843")
    facts = [
        XbrlFact(accession, "srt:ScheduleOfRealEstateProperties", 3.0),
        XbrlFact(accession, "ecd:InsiderTradingPolicyFlag", 1.0),
        XbrlFact(accession, "ifrs-full:Revenue", 5.0),
        XbrlFact(accession, "custom:Unknown", 2.0),
    ]

    result = classify_candidate_facts("us-gaap:Profit", facts)

    by_qname = {verdict.concept_qname: verdict for verdict in result}
    srt = by_qname["srt:ScheduleOfRealEstateProperties"]
    assert srt.decision == "REJECT" and srt.reject_reason == "OTHER_STATEMENT"
    for qname in ("ecd:InsiderTradingPolicyFlag", "ifrs-full:Revenue"):
        verdict = by_qname[qname]
        assert verdict.decision == "UNKNOWN"
        assert verdict.unknown_reason == "STANDARD_TAXONOMY"
    custom = by_qname["custom:Unknown"]
    assert custom.decision == "UNKNOWN"
    assert custom.unknown_reason == "UNSEEN_SIGNATURE"


def test_candidate_classification_names_closed_set_taxonomy_facts() -> None:
    accession = AccessionNumber("0000950170-24-087843")
    facts = [
        XbrlFact(accession, "rxp:Bonuses", 4.0),
        XbrlFact(accession, "cef:AcquiredFundFeesAndExpensesPercent", 0.01),
        XbrlFact(accession, "us-gaap-ebp:EmployeeBenefitPlanAsset", 9.0),
        XbrlFact(accession, "oef:ShareholderReport", 1.0),
    ]

    result = classify_candidate_facts("us-gaap:Profit", facts)

    by_qname = {verdict.concept_qname: verdict for verdict in result}
    for qname in (
        "rxp:Bonuses",
        "cef:AcquiredFundFeesAndExpensesPercent",
        "us-gaap-ebp:EmployeeBenefitPlanAsset",
    ):
        verdict = by_qname[qname]
        assert verdict.decision == "UNKNOWN"
        assert verdict.unknown_reason == "STANDARD_TAXONOMY"
    oef = by_qname["oef:ShareholderReport"]
    assert oef.decision == "UNKNOWN"
    assert oef.unknown_reason == "UNSEEN_SIGNATURE"
