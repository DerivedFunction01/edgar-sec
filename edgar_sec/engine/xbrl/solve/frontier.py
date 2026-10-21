"""Candidate frontier and antichain bridges for the constraint solver."""

from __future__ import annotations

from collections.abc import Sequence

from edgar_sec.engine.xbrl.normalize.decomposer import decompose_concept
from edgar_sec.engine.xbrl.schema.models import CalculationArc, XbrlFact
from edgar_sec.engine.xbrl.solve.antichain import (
    AntiChainOutcome,
    AntiChainValidator,
    CandidateFrontier,
)
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy


def verify_non_double_counting(
    validator: AntiChainValidator,
    taxonomy: DomainTaxonomy,
    selected_concepts: Sequence[str],
    calculation_arcs: Sequence[CalculationArc],
) -> AntiChainOutcome:
    def local(concept: str) -> str:
        return concept.split(":")[-1]

    arcs = [
        (local(arc.parent_qname), local(arc.child_qname), arc.weight)
        for arc in calculation_arcs
    ]
    graph = taxonomy.atom_relations
    lexicon = taxonomy.token_lexicon
    if graph is not None and lexicon is not None:
        atoms = {
            concept: decompose_concept(concept, lexicon)[0]
            for concept in selected_concepts
        }
        for edge in graph.relations:
            if edge.relation_type not in ("PART_OF", "CONTRA_OF"):
                continue
            if not edge.source.modifiers and not edge.target.modifiers:
                continue
            children = [c for c in atoms if atoms[c] == edge.source]
            parents = [c for c in atoms if atoms[c] == edge.target]
            if len(children) == 1 and len(parents) == 1 and children[0] != parents[0]:
                arcs.append(
                    (local(parents[0]), local(children[0]), edge.algebraic_weight)
                )
    return validator.verify_non_double_counting(
        selected_concepts=[local(concept) for concept in selected_concepts],
        calculation_arcs=arcs,
    )


def resolve_query_frontier(
    validator: AntiChainValidator,
    taxonomy: DomainTaxonomy,
    query_concept: str,
    facts: Sequence[XbrlFact],
    calculation_arcs: Sequence[CalculationArc],
) -> CandidateFrontier:
    candidates = [
        {"concept_qname": fact.concept_qname, "numeric_value": float(fact.value)}
        for fact in facts
        if isinstance(fact.value, (int, float))
    ]
    graph = taxonomy.atom_relations
    lexicon = taxonomy.token_lexicon
    contra_concepts: set[str] = set()
    if graph is not None and lexicon is not None:
        contra_edges = [
            edge for edge in graph.relations if edge.relation_type == "CONTRA_OF"
        ]
        for fact in facts:
            atom = decompose_concept(fact.concept_qname, lexicon)[0]
            if any(
                atom.is_a(edge.source) or atom.is_a(edge.target)
                for edge in contra_edges
            ):
                contra_concepts.add(fact.concept_qname)
    return validator.resolve_query_frontier(
        query_concept,
        candidates,
        [(arc.parent_qname, arc.child_qname, arc.weight) for arc in calculation_arcs],
        contra_concepts,
    )
