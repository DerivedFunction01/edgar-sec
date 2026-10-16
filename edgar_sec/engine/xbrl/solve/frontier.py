"""Candidate frontier and antichain bridges for the constraint solver."""

from __future__ import annotations

from collections.abc import Sequence

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
    if graph is not None:
        arcs.extend(
            (
                local(edge.target_concept),
                local(edge.source_concept),
                edge.algebraic_weight,
            )
            for edge in graph.relations
            if edge.relation_type in ("PART_OF", "CONTRA_OF")
            and edge.source_concept
            and edge.target_concept
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
    contra_concepts = {
        concept
        for edge in (graph.relations if graph else ())
        if edge.relation_type == "CONTRA_OF"
        for concept in (edge.source_concept, edge.target_concept)
        if concept
    }
    return validator.resolve_query_frontier(
        query_concept,
        candidates,
        [(arc.parent_qname, arc.child_qname, arc.weight) for arc in calculation_arcs],
        contra_concepts,
    )
