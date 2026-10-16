"""Evaluate reported and taxonomy-derived aggregate facts."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.normalize.decomposer import decompose_concept
from edgar_sec.engine.xbrl.schema.models import (
    AggregateFact,
    CalculationArc,
    GranularComponent,
    XbrlFact,
)
from edgar_sec.engine.xbrl.solve.antichain import AntiChainValidator
from edgar_sec.engine.xbrl.solve.breakdown import breakdown_concept
from edgar_sec.engine.xbrl.solve.frontier import verify_non_double_counting


class AggregateEvaluator:
    def __init__(
        self,
        kb: EvidenceKnowledgeBase,
        antichain_validator: AntiChainValidator,
    ) -> None:
        self.kb = kb
        self.antichain_validator = antichain_validator

    def _verify_non_double_counting(
        self,
        selected_concepts: Sequence[str],
        calculation_arcs: Sequence[CalculationArc],
    ):
        return verify_non_double_counting(
            self.antichain_validator,
            self.kb.taxonomy,
            selected_concepts,
            calculation_arcs,
        )

    def _resolve_atom_value(
        self,
        edge: Any,
        facts: Sequence[XbrlFact],
        calculation_arcs: Sequence[CalculationArc],
        *,
        visited: set[str] | None = None,
    ) -> float | None:
        lexicon = self.kb.taxonomy.token_lexicon
        source_concept = getattr(edge, "source_concept", None)
        visited_concepts = visited if visited is not None else set()
        if lexicon is not None:
            matching: list[tuple[float, int, Any]] = []
            source_local = (
                source_concept.split(":")[-1] if source_concept is not None else None
            )
            for fact in facts:
                if fact.dimensions:
                    continue
                try:
                    value = float(fact.value)
                except (TypeError, ValueError):
                    continue
                fact_atom, _, _, _ = decompose_concept(fact.concept_qname, lexicon)
                if fact_atom.is_a(edge.source):
                    exact_name = int(fact.concept_qname.split(":")[-1] == source_local)
                    matching.append((value, exact_name, fact_atom))

            if matching:
                matching.sort(
                    key=lambda item: (len(item[2].modifiers), item[1]), reverse=True
                )
                return matching[0][0]

        if source_concept:
            source_local = source_concept.split(":")[-1]
            for fact in facts:
                if fact.dimensions or fact.concept_qname.split(":")[-1] != source_local:
                    continue
                try:
                    return float(fact.value)
                except (TypeError, ValueError):
                    continue

            if source_concept not in visited_concepts:
                visited_concepts.add(source_concept)
                aggregate = self.evaluate_goal(
                    source_concept,
                    facts,
                    calculation_arcs,
                    _visited=visited_concepts,
                )
                if aggregate.value is not None:
                    return aggregate.value

        if lexicon is None:
            return None

        head_def = self.kb.taxonomy.prime_head(edge.source.head)
        canonical_concept = head_def.canonical_concept if head_def else None
        if canonical_concept and canonical_concept not in visited_concepts:
            visited_concepts.add(canonical_concept)
            sub_aggregate = self.evaluate_goal(
                canonical_concept,
                facts,
                calculation_arcs,
                _visited=visited_concepts,
            )
            if sub_aggregate.value is not None:
                return sub_aggregate.value

        return None

    def evaluate_goal(
        self,
        target_concept: str,
        facts: Sequence[XbrlFact],
        calculation_arcs: Sequence[CalculationArc] = (),
        *,
        axis_filter: str | None = None,
        entity: str = "",
        period: str = "",
        unit: str = "USD",
        _visited: set[str] | None = None,
    ) -> AggregateFact:
        if axis_filter is not None:
            breakdown = breakdown_concept(
                self.kb, target_concept, facts, calculation_arcs, axis=axis_filter
            )
            if breakdown.components:
                total = sum(
                    component.value * component.weight
                    for component in breakdown.components
                )
                path = tuple(
                    f"{component.identifier}={component.value}"
                    for component in breakdown.components
                )
                return AggregateFact(
                    measure_id=target_concept,
                    entity=entity,
                    period=period,
                    unit=unit,
                    value=round(total, 4),
                    basis="DERIVED_EXACT",
                    slice_dimensions={axis_filter: "*"},
                    components=breakdown.components,
                    residual=breakdown.discrepancy,
                    derivation_path=path,
                    breakdown=breakdown,
                    resolution_tier="DIMENSIONAL_ANTICHAIN_SUM",
                )

        target_local = target_concept.split(":")[-1]
        fact_vals = {
            fact.concept_qname: float(fact.value)
            for fact in facts
            if not fact.dimensions and isinstance(fact.value, (int, float))
        }
        local_fact_vals = {
            fact.concept_qname.split(":")[-1]: float(fact.value)
            for fact in facts
            if not fact.dimensions and isinstance(fact.value, (int, float))
        }

        direct_val = fact_vals.get(target_concept, local_fact_vals.get(target_local))
        resolved_concept = target_concept
        if direct_val is None:
            for candidate in self.kb.taxonomy.equivalent_concepts(target_local):
                candidate_val = fact_vals.get(
                    candidate, local_fact_vals.get(candidate.split(":")[-1])
                )
                if candidate_val is not None:
                    direct_val = candidate_val
                    resolved_concept = candidate
                    break

        lexicon = self.kb.taxonomy.token_lexicon
        if direct_val is None and lexicon is not None:
            target_atom, _, _, _ = decompose_concept(target_concept, lexicon)
            for fact in facts:
                if fact.dimensions or not isinstance(fact.value, (int, float)):
                    continue
                fact_atom, _, _, _ = decompose_concept(fact.concept_qname, lexicon)
                if fact_atom == target_atom:
                    direct_val = float(fact.value)
                    resolved_concept = fact.concept_qname
                    break

        if direct_val is not None:
            breakdown = breakdown_concept(
                self.kb, resolved_concept, facts, calculation_arcs
            )
            outcome = self._verify_non_double_counting(
                [component.identifier for component in breakdown.components],
                calculation_arcs,
            )
            if outcome.violations:
                return AggregateFact(
                    measure_id=target_concept,
                    entity=entity,
                    period=period,
                    unit=unit,
                    value=direct_val,
                    basis="CONFLICT_DOUBLE_COUNTING",
                    components=breakdown.components,
                    residual=breakdown.discrepancy,
                    derivation_path=outcome.violations,
                    breakdown=breakdown,
                    resolution_tier="ANTICHAIN_CONFLICT",
                )
            basis = (
                "REPORTED_VERIFIED"
                if breakdown.components and breakdown.is_balanced
                else "CONFLICT"
                if breakdown.components
                else "REPORTED"
            )
            return AggregateFact(
                measure_id=target_concept,
                entity=entity,
                period=period,
                unit=unit,
                value=direct_val,
                basis=basis,
                components=breakdown.components,
                residual=breakdown.discrepancy,
                breakdown=breakdown,
                resolution_tier="DIRECT_ANCHOR",
            )

        child_arcs = [
            arc
            for arc in calculation_arcs
            if arc.parent_qname == target_concept
            or arc.parent_qname.split(":")[-1] == target_local
        ]
        if child_arcs:
            total = 0.0
            path: list[str] = []
            all_resolved = True
            for arc in child_arcs:
                value = fact_vals.get(
                    arc.child_qname,
                    local_fact_vals.get(arc.child_qname.split(":")[-1]),
                )
                if value is None:
                    all_resolved = False
                    break
                total += value * arc.weight
                path.append(f"{arc.child_qname} * {arc.weight}")
            if all_resolved and path:
                outcome = self._verify_non_double_counting(
                    [arc.child_qname for arc in child_arcs], calculation_arcs
                )
                breakdown = breakdown_concept(
                    self.kb, target_concept, facts, calculation_arcs
                )
                if outcome.violations:
                    return AggregateFact(
                        measure_id=target_concept,
                        entity=entity,
                        period=period,
                        unit=unit,
                        value=None,
                        basis="CONFLICT_DOUBLE_COUNTING",
                        components=breakdown.components,
                        residual=breakdown.discrepancy,
                        derivation_path=outcome.violations,
                        breakdown=breakdown,
                        resolution_tier="ANTICHAIN_CONFLICT",
                    )
                return AggregateFact(
                    measure_id=target_concept,
                    entity=entity,
                    period=period,
                    unit=unit,
                    value=round(total, 4),
                    basis="DERIVED_EXACT",
                    components=breakdown.components,
                    residual=breakdown.discrepancy,
                    derivation_path=tuple(path),
                    breakdown=breakdown,
                    resolution_tier="DERIVED_MULTI_HOP",
                )

        atom_graph = self.kb.taxonomy.atom_relations
        if atom_graph is not None and lexicon is not None:
            target_atom, _, _, _ = decompose_concept(target_concept, lexicon)
            concept_edges = [
                edge
                for edge in atom_graph.relations
                if edge.relation_type in ("PART_OF", "CONTRA_OF", "DERIVED_FROM")
                and edge.target_concept
                and edge.target_concept.split(":")[-1] == target_local
            ]
            if concept_edges:
                incoming_edges = concept_edges
            else:
                atom_edges = [
                    edge
                    for edge in atom_graph.relations
                    if edge.relation_type in ("PART_OF", "CONTRA_OF", "DERIVED_FROM")
                    and target_atom.is_a(edge.target)
                ]
                specificity = max(
                    (len(edge.target.modifiers) for edge in atom_edges), default=-1
                )
                incoming_edges = [
                    edge
                    for edge in atom_edges
                    if len(edge.target.modifiers) == specificity
                ]

            edge_groups: dict[str, list[Any]] = {}
            for edge in incoming_edges:
                key = getattr(edge, "formula_id", None) or edge.edge_id
                edge_groups.setdefault(key, []).append(edge)

            for group_edges in edge_groups.values():
                resolved_vals: list[tuple[float, Any]] = []
                for edge in group_edges:
                    value = self._resolve_atom_value(
                        edge, facts, calculation_arcs, visited=_visited
                    )
                    if value is None:
                        break
                    resolved_vals.append((value, edge))

                if len(resolved_vals) != len(group_edges) or not resolved_vals:
                    continue
                outcome = self._verify_non_double_counting(
                    [
                        edge.source_concept or str(edge.source)
                        for _, edge in resolved_vals
                    ],
                    calculation_arcs,
                )
                components = tuple(
                    GranularComponent(
                        identifier=edge.source_concept or str(edge.source),
                        value=value,
                        weight=edge.algebraic_weight,
                    )
                    for value, edge in resolved_vals
                )
                if outcome.violations:
                    return AggregateFact(
                        measure_id=target_concept,
                        entity=entity,
                        period=period,
                        unit=unit,
                        value=None,
                        basis="CONFLICT_DOUBLE_COUNTING",
                        components=components,
                        derivation_path=outcome.violations,
                        resolution_tier="ANTICHAIN_CONFLICT",
                    )
                total = sum(
                    value * edge.algebraic_weight for value, edge in resolved_vals
                )
                path = tuple(
                    f"{edge.source}({value}) * {edge.algebraic_weight}"
                    for value, edge in resolved_vals
                )
                return AggregateFact(
                    measure_id=target_concept,
                    entity=entity,
                    period=period,
                    unit=unit,
                    value=round(total, 4),
                    basis="DERIVED_EXACT",
                    components=components,
                    derivation_path=path,
                    resolution_tier="SUBATOMIC_ALGEBRAIC_IDENTITY",
                )

        return AggregateFact(
            measure_id=target_concept,
            entity=entity,
            period=period,
            unit=unit,
            value=None,
            basis="NOT_AVAILABLE",
            resolution_tier="UNRESOLVED",
        )
