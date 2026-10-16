from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.schema.models import XbrlFact
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
