"""Constraint-satisfaction graph solver and multi-hop financial derivation engine."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from edgar_sec.engine.xbrl.atoms import Atom
from edgar_sec.engine.xbrl.decomposer import decompose_concept, infer_semantic_frame
from edgar_sec.engine.xbrl.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.gold import PlacementPrediction
from edgar_sec.engine.xbrl.models import (
    AggregateFact,
    CalculationArc,
    ConceptBreakdown,
    GranularComponent,
    PresentationArc,
    Verdict,
    XbrlFact,
)


class XbrlConstraintSolver:
    """Graph solver reconciling XBRL facts, calculation linkbases, and declarative rules."""

    def __init__(
        self,
        kb: EvidenceKnowledgeBase,
        *,
        enable_head_induction: bool = True,
    ) -> None:
        self.kb = kb
        self.enable_head_induction = enable_head_induction

    def solve_placements(
        self,
        facts: Sequence[XbrlFact],
        calculation_arcs: Sequence[CalculationArc],
        *,
        firm: str = "",
        sector: str = "",
        year: int | str = "",
    ) -> tuple[PlacementPrediction, ...]:
        """Determine target parent node and algebraic weight for extension facts."""
        calc_parents: dict[str, tuple[str, float]] = {
            arc.child_qname: (arc.parent_qname, arc.weight) for arc in calculation_arcs
        }
        predictions: list[PlacementPrediction] = []

        for fact in facts:
            qname = fact.concept_qname
            # 1. Check published calculation arc
            if qname in calc_parents:
                parent, weight = calc_parents[qname]
                predictions.append(
                    PlacementPrediction(
                        concept_qname=qname,
                        predicted_parent=parent,
                        predicted_weight=weight,
                        is_abstained=False,
                    )
                )
                continue

            # 2. Check KB unification rules with 4-tier scope backoff
            best_rule = None
            best_spec = 0
            for rule in self.kb.rules:
                if rule.concept_qname == qname:
                    spec, _ = self.kb.scope_specificity(rule.scope, firm, sector, year)
                    if spec > best_spec:
                        best_spec = spec
                        best_rule = rule

            if best_rule is not None:
                predictions.append(
                    PlacementPrediction(
                        concept_qname=qname,
                        predicted_parent=best_rule.target_node,
                        predicted_weight=best_rule.weight,
                        is_abstained=False,
                    )
                )
                continue

            # 3. Subatomic prime head induction via declarative taxonomy graph
            if (
                self.enable_head_induction
                and self.kb.taxonomy.atom_relations is not None
            ):
                lexicon = self.kb.taxonomy.token_lexicon
                if lexicon is not None:
                    atom, _, _, _ = decompose_concept(qname, lexicon)
                else:
                    frame = infer_semantic_frame(
                        qname,
                        self.kb.taxonomy,
                        unit=fact.unit,
                        balance=fact.balance,
                    )
                    atom = Atom(frame.prime_head, frozenset(frame.modifiers))
                edges = self.kb.taxonomy.atom_relations.find_inherited_edges(
                    atom, "PART_OF"
                )
                if edges:
                    best_edge = edges[0]
                    head_def = self.kb.taxonomy.prime_head(best_edge.target.head)
                    target_concept = best_edge.target_concept or (
                        head_def.canonical_concept
                        if (head_def and head_def.canonical_concept)
                        else best_edge.target.head
                    )
                    pred_parent = (
                        f"us-gaap:{target_concept}"
                        if ":" not in target_concept
                        else target_concept
                    )
                    predictions.append(
                        PlacementPrediction(
                            concept_qname=qname,
                            predicted_parent=pred_parent,
                            predicted_weight=best_edge.algebraic_weight,
                            is_abstained=False,
                        )
                    )
                    continue

            # 4. Abstain if unresolvable
            predictions.append(
                PlacementPrediction(
                    concept_qname=qname,
                    predicted_parent=None,
                    predicted_weight=None,
                    is_abstained=True,
                )
            )

        return tuple(predictions)

    def breakdown_concept(
        self,
        target_concept: str,
        facts: Sequence[XbrlFact],
        calculation_arcs: Sequence[CalculationArc] = (),
        *,
        axis: str | None = None,
    ) -> ConceptBreakdown:
        """Decompose a financial concept into granular components via axis or calculation arcs."""
        target_local = (
            target_concept.split(":")[-1] if ":" in target_concept else target_concept
        )

        if axis is not None:
            axis_local = axis.split(":")[-1] if ":" in axis else axis
            components: list[GranularComponent] = []
            for f in facts:
                c_local = (
                    f.concept_qname.split(":")[-1]
                    if ":" in f.concept_qname
                    else f.concept_qname
                )
                if c_local == target_local and f.dimensions:
                    for d_axis, d_member in f.dimensions.items():
                        d_axis_local = (
                            d_axis.split(":")[-1] if ":" in d_axis else d_axis
                        )
                        if d_axis_local == axis_local and isinstance(
                            f.value, (int, float)
                        ):
                            components.append(
                                GranularComponent(
                                    identifier=d_member,
                                    value=float(f.value),
                                    weight=1.0,
                                    member_dimension=d_axis,
                                )
                            )

            # Apply antichain cut: prevent ancestor and descendant from co-existing
            pruned_components: list[GranularComponent] = []
            for comp in components:
                has_ancestor_present = any(
                    comp.identifier != other.identifier
                    and self.kb.is_geo_subsumed(comp.identifier, other.identifier)
                    for other in components
                )
                if not has_ancestor_present:
                    pruned_components.append(comp)
            components = pruned_components if pruned_components else components

            top_val = None
            for f in facts:
                c_local = (
                    f.concept_qname.split(":")[-1]
                    if ":" in f.concept_qname
                    else f.concept_qname
                )
                if (
                    c_local == target_local
                    and not f.dimensions
                    and isinstance(f.value, (int, float))
                ):
                    top_val = float(f.value)
                    break

            comp_sum = sum(c.value * c.weight for c in components)
            discrepancy = (
                round(abs(comp_sum - top_val), 4) if top_val is not None else 0.0
            )
            is_balanced = top_val is None or discrepancy < 1.0
            return ConceptBreakdown(
                target_concept=target_concept,
                total_value=top_val,
                components=tuple(components),
                is_balanced=is_balanced,
                discrepancy=discrepancy,
            )

        child_arcs = [
            a
            for a in calculation_arcs
            if (
                a.parent_qname == target_concept
                or a.parent_qname.split(":")[-1] == target_local
            )
        ]
        calc_components: list[GranularComponent] = []
        fact_map = {
            f.concept_qname: float(f.value)
            for f in facts
            if not f.dimensions and isinstance(f.value, (int, float))
        }
        local_fact_map = {
            f.concept_qname.split(":")[-1]: float(f.value)
            for f in facts
            if not f.dimensions and isinstance(f.value, (int, float))
        }

        for arc in child_arcs:
            c_q = arc.child_qname
            c_loc = c_q.split(":")[-1]
            val = fact_map.get(c_q, local_fact_map.get(c_loc))
            if val is not None:
                calc_components.append(
                    GranularComponent(
                        identifier=c_q,
                        value=val,
                        weight=arc.weight,
                    )
                )

        top_val = fact_map.get(target_concept, local_fact_map.get(target_local))
        comp_sum = sum(c.value * c.weight for c in calc_components)
        discrepancy = round(abs(comp_sum - top_val), 4) if top_val is not None else 0.0
        is_balanced = top_val is None or discrepancy < 1.0

        return ConceptBreakdown(
            target_concept=target_concept,
            total_value=top_val,
            components=tuple(calc_components),
            is_balanced=is_balanced,
            discrepancy=discrepancy,
        )

    def classify_candidate_facts(
        self,
        target_concept: str,
        facts: Sequence[XbrlFact],
        calculation_arcs: Sequence[CalculationArc] = (),
    ) -> tuple[Verdict, ...]:
        """Classify candidate facts into ACCEPT, REJECT, or UNKNOWN with materiality priority."""
        target_local = (
            target_concept.split(":")[-1] if ":" in target_concept else target_concept
        )
        child_arc_map = {
            a.child_qname: a.weight
            for a in calculation_arcs
            if (
                a.parent_qname == target_concept
                or a.parent_qname.split(":")[-1] == target_local
            )
        }
        child_locals = {k.split(":")[-1] for k in child_arc_map}

        max_val = 1.0
        for f in facts:
            if isinstance(f.value, (int, float)):
                max_val = max(max_val, abs(float(f.value)))

        verdicts: list[Verdict] = []
        for f in facts:
            qname = f.concept_qname
            q_loc = qname.split(":")[-1]
            val = float(f.value) if isinstance(f.value, (int, float)) else 0.0
            prio = round(abs(val) / max_val, 4)

            if qname == target_concept or q_loc == target_local:
                role = "LEAF" if f.dimensions else "ROOT"
                verdicts.append(
                    Verdict(
                        concept_qname=qname,
                        measure_id=target_concept,
                        decision="ACCEPT",
                        role=role,
                        weight=1.0,
                        priority=prio,
                    )
                )
                continue

            if qname in child_arc_map or q_loc in child_locals:
                w = child_arc_map.get(qname, 1.0)
                verdicts.append(
                    Verdict(
                        concept_qname=qname,
                        measure_id=target_concept,
                        decision="ACCEPT",
                        role="LEAF",
                        weight=w,
                        priority=prio,
                    )
                )
                continue

            if not isinstance(f.value, (int, float)):
                verdicts.append(
                    Verdict(
                        concept_qname=qname,
                        measure_id=target_concept,
                        decision="REJECT",
                        reject_reason="NON_NUMERIC_PROSE",
                        priority=0.0,
                    )
                )
                continue

            if (
                ":" in qname
                and not qname.startswith("us-gaap:")
                and not qname.startswith("dei:")
            ):
                verdicts.append(
                    Verdict(
                        concept_qname=qname,
                        measure_id=target_concept,
                        decision="UNKNOWN",
                        unknown_reason="UNSEEN_SIGNATURE",
                        priority=prio,
                    )
                )
            else:
                verdicts.append(
                    Verdict(
                        concept_qname=qname,
                        measure_id=target_concept,
                        decision="REJECT",
                        reject_reason="OTHER_STATEMENT",
                        priority=prio,
                    )
                )

        return tuple(verdicts)

    def _resolve_source_node_value(
        self,
        node_name: str,
        fact_vals: dict[str, float],
        local_fact_vals: dict[str, float],
        facts: Sequence[XbrlFact],
        calculation_arcs: Sequence[CalculationArc],
    ) -> float | None:
        """Resolve value for a relational source node directly, via aliases, or recursively."""
        node_local = node_name.split(":")[-1]
        direct_val = fact_vals.get(node_name, local_fact_vals.get(node_local))
        if direct_val is not None:
            return direct_val

        # Declarative equivalence traversal over SAME_CONCEPT taxonomy relations
        equivalences = self.kb.taxonomy.equivalent_concepts(node_local)
        for cand in equivalences:
            val = fact_vals.get(cand, local_fact_vals.get(cand.split(":")[-1]))
            if val is not None:
                return val

        sub_fact = self.evaluate_goal(node_name, facts, calculation_arcs)
        return sub_fact.value

    def _resolve_atom_value(
        self,
        edge: Any,
        facts: Sequence[XbrlFact],
        calculation_arcs: Sequence[CalculationArc],
        *,
        visited: set[str] | None = None,
    ) -> float | None:
        """Resolve value for an atom relation source directly from facts or recursively."""
        lexicon = self.kb.taxonomy.token_lexicon
        if lexicon is None:
            return None

        matching: list[tuple[float, Atom]] = []
        for f in facts:
            if f.dimensions:
                continue
            v = None
            if isinstance(f.value, (int, float)):
                v = float(f.value)
            elif isinstance(f.value, str):
                try:
                    v = float(f.value)
                except ValueError:
                    pass
            if v is None:
                continue
            f_atom, _, _, _ = decompose_concept(f.concept_qname, lexicon)
            if f_atom.is_a(edge.source):
                matching.append((v, f_atom))

        if matching:
            matching.sort(key=lambda item: len(item[1].modifiers))
            return matching[0][0]

        v_set = visited if visited is not None else set()
        head_def = self.kb.taxonomy.prime_head(edge.source.head)
        source_concept = getattr(edge, "source_concept", None) or (
            head_def.canonical_concept if head_def else None
        )
        if source_concept and source_concept not in v_set:
            v_set.add(source_concept)
            sub_agg = self.evaluate_goal(
                source_concept, facts, calculation_arcs, _visited=v_set
            )
            if sub_agg.value is not None:
                return sub_agg.value

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
        """Evaluate an aggregate financial fact emitting canonical basis and derivation path."""
        if axis_filter is not None:
            bd = self.breakdown_concept(
                target_concept, facts, calculation_arcs, axis=axis_filter
            )
            if bd.components:
                total = sum(c.value * c.weight for c in bd.components)
                path = tuple(f"{c.identifier}={c.value}" for c in bd.components)
                return AggregateFact(
                    measure_id=target_concept,
                    entity=entity,
                    period=period,
                    unit=unit,
                    value=round(total, 4),
                    basis="DERIVED_EXACT",
                    slice_dimensions={axis_filter: "*"},
                    components=bd.components,
                    residual=bd.discrepancy,
                    derivation_path=path,
                    breakdown=bd,
                    resolution_tier="DIMENSIONAL_ANTICHAIN_SUM",
                )

        target_local = (
            target_concept.split(":")[-1] if ":" in target_concept else target_concept
        )
        fact_vals: dict[str, float] = {
            f.concept_qname: float(f.value)
            for f in facts
            if not f.dimensions and isinstance(f.value, (int, float))
        }
        local_fact_vals: dict[str, float] = {
            f.concept_qname.split(":")[-1]: float(f.value)
            for f in facts
            if not f.dimensions and isinstance(f.value, (int, float))
        }

        # 1. Direct fact match or equivalent concept match
        direct_val = fact_vals.get(target_concept, local_fact_vals.get(target_local))
        resolved_concept = target_concept
        if direct_val is None:
            equivs = self.kb.taxonomy.equivalent_concepts(target_local)
            for cand in equivs:
                cand_val = fact_vals.get(cand, local_fact_vals.get(cand.split(":")[-1]))
                if cand_val is not None:
                    direct_val = cand_val
                    resolved_concept = cand
                    break

        lexicon = self.kb.taxonomy.token_lexicon
        if direct_val is None and lexicon is not None:
            target_atom, _, _, _ = decompose_concept(target_concept, lexicon)
            for f in facts:
                if f.dimensions or not isinstance(f.value, (int, float)):
                    continue
                f_atom, _, _, _ = decompose_concept(f.concept_qname, lexicon)
                if f_atom == target_atom:
                    direct_val = float(f.value)
                    resolved_concept = f.concept_qname
                    break

        if direct_val is not None:
            bd = self.breakdown_concept(resolved_concept, facts, calculation_arcs)
            if bd.components:
                basis = "REPORTED_VERIFIED" if bd.is_balanced else "CONFLICT"
            else:
                basis = "REPORTED"
            return AggregateFact(
                measure_id=target_concept,
                entity=entity,
                period=period,
                unit=unit,
                value=direct_val,
                basis=basis,
                components=bd.components,
                residual=bd.discrepancy,
                breakdown=bd,
                resolution_tier="DIRECT_ANCHOR",
            )

        # 2. Multi-hop derivation via calculation arcs
        child_arcs = [
            a
            for a in calculation_arcs
            if a.parent_qname == target_concept
            or a.parent_qname.split(":")[-1] == target_local
        ]
        if child_arcs:
            total = 0.0
            path: list[str] = []
            all_resolved = True
            for arc in child_arcs:
                val = fact_vals.get(
                    arc.child_qname,
                    local_fact_vals.get(arc.child_qname.split(":")[-1]),
                )
                if val is not None:
                    total += val * arc.weight
                    path.append(f"{arc.child_qname} * {arc.weight}")
                else:
                    all_resolved = False
                    break
            if all_resolved and path:
                bd = self.breakdown_concept(target_concept, facts, calculation_arcs)
                return AggregateFact(
                    measure_id=target_concept,
                    entity=entity,
                    period=period,
                    unit=unit,
                    value=round(total, 4),
                    basis="DERIVED_EXACT",
                    components=bd.components,
                    residual=bd.discrepancy,
                    derivation_path=tuple(path),
                    breakdown=bd,
                    resolution_tier="DERIVED_MULTI_HOP",
                )

        # 3. Declarative Relational Graph Traversal over Atom Coordinates
        atom_graph = self.kb.taxonomy.atom_relations
        if atom_graph is not None and lexicon is not None:
            target_atom, _, _, _ = decompose_concept(target_concept, lexicon)
            incoming_edges = [
                e
                for e in atom_graph.relations
                if e.relation_type in ("PART_OF", "CONTRA_OF", "DERIVED_FROM")
                and (
                    target_atom.is_a(e.target)
                    or (
                        e.target_concept
                        and e.target_concept.split(":")[-1] == target_local
                    )
                )
            ]
            if incoming_edges:
                edge_groups: dict[str, list[Any]] = {}
                for e in incoming_edges:
                    key = getattr(e, "formula_id", None) or e.edge_id
                    edge_groups.setdefault(key, []).append(e)

                for group_edges in edge_groups.values():
                    resolved_vals: list[tuple[float, Any]] = []
                    all_found = True
                    for edge in group_edges:
                        val = self._resolve_atom_value(
                            edge, facts, calculation_arcs, visited=_visited
                        )
                        if val is not None:
                            resolved_vals.append((val, edge))
                        else:
                            all_found = False
                            break

                    if all_found and resolved_vals:
                        total = sum(v * e.algebraic_weight for v, e in resolved_vals)
                        path = tuple(
                            f"{e.source}({v}) * {e.algebraic_weight}"
                            for v, e in resolved_vals
                        )
                        return AggregateFact(
                            measure_id=target_concept,
                            entity=entity,
                            period=period,
                            unit=unit,
                            value=round(total, 4),
                            basis="DERIVED_EXACT",
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
