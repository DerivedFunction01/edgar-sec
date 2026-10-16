"""Build dimensional and calculation-arc concept breakdowns."""

from __future__ import annotations

from collections.abc import Sequence

from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.schema.models import (
    CalculationArc,
    ConceptBreakdown,
    GranularComponent,
    XbrlFact,
)


def _local_name(qname: str) -> str:
    return qname.split(":")[-1]


def breakdown_concept(
    kb: EvidenceKnowledgeBase,
    target_concept: str,
    facts: Sequence[XbrlFact],
    calculation_arcs: Sequence[CalculationArc] = (),
    *,
    axis: str | None = None,
) -> ConceptBreakdown:
    target_local = _local_name(target_concept)

    if axis is not None:
        axis_local = _local_name(axis)
        components: list[GranularComponent] = []
        for fact in facts:
            if _local_name(fact.concept_qname) != target_local or not fact.dimensions:
                continue
            for dim_axis, dim_member in fact.dimensions.items():
                if _local_name(dim_axis) == axis_local and isinstance(
                    fact.value, (int, float)
                ):
                    components.append(
                        GranularComponent(
                            identifier=dim_member,
                            value=float(fact.value),
                            weight=1.0,
                            member_dimension=dim_axis,
                        )
                    )

        pruned_components = [
            component
            for component in components
            if not any(
                component.identifier != other.identifier
                and kb.is_geo_subsumed(component.identifier, other.identifier)
                for other in components
            )
        ]
        components = pruned_components if pruned_components else components

        top_val = next(
            (
                float(fact.value)
                for fact in facts
                if _local_name(fact.concept_qname) == target_local
                and not fact.dimensions
                and isinstance(fact.value, (int, float))
            ),
            None,
        )
        comp_sum = sum(component.value * component.weight for component in components)
        discrepancy = round(abs(comp_sum - top_val), 4) if top_val is not None else 0.0
        return ConceptBreakdown(
            target_concept=target_concept,
            total_value=top_val,
            components=tuple(components),
            is_balanced=top_val is None or discrepancy < 1.0,
            discrepancy=discrepancy,
        )

    child_arcs = [
        arc
        for arc in calculation_arcs
        if arc.parent_qname == target_concept
        or _local_name(arc.parent_qname) == target_local
    ]
    fact_map = {
        fact.concept_qname: float(fact.value)
        for fact in facts
        if not fact.dimensions and isinstance(fact.value, (int, float))
    }
    local_fact_map = {
        _local_name(fact.concept_qname): float(fact.value)
        for fact in facts
        if not fact.dimensions and isinstance(fact.value, (int, float))
    }

    calc_components = []
    for arc in child_arcs:
        value = fact_map.get(
            arc.child_qname, local_fact_map.get(_local_name(arc.child_qname))
        )
        if value is not None:
            calc_components.append(
                GranularComponent(
                    identifier=arc.child_qname,
                    value=value,
                    weight=arc.weight,
                )
            )

    top_val = fact_map.get(target_concept, local_fact_map.get(target_local))
    comp_sum = sum(component.value * component.weight for component in calc_components)
    discrepancy = round(abs(comp_sum - top_val), 4) if top_val is not None else 0.0
    return ConceptBreakdown(
        target_concept=target_concept,
        total_value=top_val,
        components=tuple(calc_components),
        is_balanced=top_val is None or discrepancy < 1.0,
        discrepancy=discrepancy,
    )
