from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.schema.models import CalculationArc, XbrlFact
from edgar_sec.engine.xbrl.solve.antichain import AntiChainValidator
from edgar_sec.engine.xbrl.solve.evaluation import AggregateEvaluator
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy


def test_evaluator_returns_direct_fact_anchor() -> None:
    evaluator = AggregateEvaluator(
        EvidenceKnowledgeBase(load_domain_taxonomy()), AntiChainValidator()
    )
    fact = XbrlFact(AccessionNumber("0000950170-24-087843"), "us-gaap:Revenue", 12.0)

    result = evaluator.evaluate_goal("us-gaap:Revenue", [fact])

    assert result.value == 12.0
    assert result.basis == "REPORTED"


def _evaluator() -> AggregateEvaluator:
    return AggregateEvaluator(
        EvidenceKnowledgeBase(load_domain_taxonomy()), AntiChainValidator()
    )


_TARGET = "us-gaap:LiabilitiesAndStockholdersEquity"
_ARCS = (
    CalculationArc(_TARGET, "us-gaap:Liabilities", weight=1.0),
    CalculationArc(_TARGET, "us-gaap:CommitmentsAndContingencies", weight=1.0),
    CalculationArc(_TARGET, "us-gaap:StockholdersEquity", weight=1.0),
)


def test_calc_derivation_skips_nil_reported_child() -> None:
    """A nil-reported calc child contributes nothing to the calc sum."""
    acc = AccessionNumber("0000000000-25-000001")
    facts = [
        XbrlFact(acc, "us-gaap:Liabilities", 100.0),
        XbrlFact(acc, "us-gaap:CommitmentsAndContingencies", None),
        XbrlFact(acc, "us-gaap:StockholdersEquity", 200.0),
    ]

    result = _evaluator().evaluate_goal(_TARGET, facts, _ARCS)

    assert result.value == 300.0
    assert result.basis == "DERIVED_EXACT"
    assert result.resolution_tier == "DERIVED_MULTI_HOP"


def test_calc_derivation_absent_child_still_blocks() -> None:
    """An absent calc child blocks the calc path; the identity fallback runs."""
    acc = AccessionNumber("0000000000-25-000001")
    facts = [
        XbrlFact(acc, "us-gaap:Liabilities", 100.0),
        XbrlFact(acc, "us-gaap:StockholdersEquity", 200.0),
    ]

    result = _evaluator().evaluate_goal(_TARGET, facts, _ARCS)

    assert result.value == 300.0
    assert result.resolution_tier == "SUBATOMIC_ALGEBRAIC_IDENTITY"
