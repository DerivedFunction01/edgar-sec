from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.schema.models import CalculationArc, XbrlFact
from edgar_sec.engine.xbrl.solve import placement
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


def test_candidate_index_decomposes_each_candidate_once(monkeypatch) -> None:
    taxonomy = load_domain_taxonomy()
    lexicon = taxonomy.token_lexicon
    assert lexicon is not None
    calls: list[str] = []
    real_decompose = placement.decompose_concept

    def counting_decompose(qname, lex, *args, **kwargs):
        calls.append(qname)
        return real_decompose(qname, lex, *args, **kwargs)

    monkeypatch.setattr(placement, "decompose_concept", counting_decompose)
    fact = XbrlFact(AccessionNumber("0000950170-24-087843"), "custom:Revenue", 10.0)
    arc = CalculationArc("us-gaap:GrossProfit", "custom:Revenue", 1.0)

    index = placement._CandidateAtomIndex(lexicon, [fact, fact], [arc])

    assert sorted(calls) == ["custom:Revenue", "us-gaap:GrossProfit"]
    atom = index.atom_for("us-gaap:GrossProfit")
    assert index.concept_for_atom(atom) == "us-gaap:GrossProfit"
    assert index.concept_for_atom(atom) == "us-gaap:GrossProfit"
    assert index.atom_for("custom:Revenue") is not None
    assert len(calls) == 2
