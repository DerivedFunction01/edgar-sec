"""Evaluate reported and taxonomy-derived aggregate facts."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.schema.models import (
    AggregateFact,
    CalculationArc,
    GranularComponent,
    XbrlFact,
    qname_local,
)
from edgar_sec.engine.xbrl.solve.antichain import AntiChainValidator
from edgar_sec.engine.xbrl.solve.breakdown import breakdown_concept
from edgar_sec.engine.xbrl.solve.frontier import verify_non_double_counting
from edgar_sec.engine.xbrl.solve.identities import eps_diluted, eps_identity_legs


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
        source_atom: Any,
        facts: Sequence[XbrlFact],
        calculation_arcs: Sequence[CalculationArc],
        *,
        visited: set[str] | None = None,
        excluded: frozenset[str] = frozenset(),
        preferred: frozenset[str] = frozenset(),
    ) -> tuple[float | None, str | None]:
        lexicon = self.kb.taxonomy.token_lexicon
        visited_concepts = visited if visited is not None else set()
        if lexicon is None:
            return None, None

        def _matching(pool: Sequence[XbrlFact]) -> list[tuple[float, int, str]]:
            found: list[tuple[float, int, str]] = []
            for fact in pool:
                if fact.dimensions or fact.concept_qname in excluded:
                    continue
                try:
                    value = float(fact.value)
                except (TypeError, ValueError):
                    continue
                fact_atom, _, _, _ = self.kb.decomposition(fact.concept_qname)
                if fact_atom.is_a(source_atom):
                    found.append((value, len(fact_atom.modifiers), fact.concept_qname))
            return found

        matching = (
            _matching([f for f in facts if f.concept_qname in preferred])
            if preferred
            else []
        )
        if not matching:
            matching = _matching(facts)

        if matching:
            # The fact denoting the term most nearly wins: candidates are
            # ranked by atom distance from the term (fewest extra
            # modifiers), never by how elaborated the candidate is.
            matching.sort(key=lambda item: item[1])
            value, _, qname = matching[0]
            return value, qname

        key = str(source_atom)
        if key not in visited_concepts:
            visited_concepts.add(key)
            sub_aggregate = self._derive_atom(
                source_atom,
                facts,
                calculation_arcs,
                visited_concepts,
                measure_id=key,
                entity="",
                period="",
                unit="USD",
            )
            if sub_aggregate is not None and sub_aggregate.value is not None:
                return sub_aggregate.value, key

        return None, None

    def _derive_atom(
        self,
        target_atom: Any,
        facts: Sequence[XbrlFact],
        calculation_arcs: Sequence[CalculationArc],
        visited: set[str] | None,
        *,
        measure_id: str,
        entity: str,
        period: str,
        unit: str,
    ) -> AggregateFact | None:
        atom_graph = self.kb.taxonomy.atom_relations
        lexicon = self.kb.taxonomy.token_lexicon
        if atom_graph is None or lexicon is None:
            return None
        target_concept = measure_id
        _visited = visited

        # Only complete identities derive: a formula of at least two
        # PART_OF/CONTRA_OF edges. A lone edge asserts that a term
        # participates in a total, never what the total is.
        edge_groups: dict[str, list[Any]] = {}
        for edge in atom_graph.relations:
            if edge.relation_type not in ("PART_OF", "CONTRA_OF"):
                continue
            key = getattr(edge, "formula_id", None) or edge.edge_id
            edge_groups.setdefault(key, []).append(edge)
        complete_groups = [
            (key, group_edges)
            for key, group_edges in edge_groups.items()
            if len(group_edges) >= 2
        ]

        fact_qnames = {fact.concept_qname for fact in facts}
        attempts: list[tuple[int, Any, tuple, float, tuple[str, ...]]] = []
        forward = [
            (key, group_edges)
            for key, group_edges in complete_groups
            if target_atom.is_a(group_edges[0].target)
        ]
        specificity = max(
            (len(group_edges[0].target.modifiers) for _, group_edges in forward),
            default=-1,
        )
        # As filed by this filer, a formula's terms are the total
        # concept's own calculation children; term resolution prefers
        # facts carried by those children over atom look-alikes filed
        # in unrelated schedules.
        child_qnames = frozenset(
            arc.child_qname
            for arc in calculation_arcs
            if arc.parent_qname == target_concept
        )
        for key, group_edges in forward:
            if len(group_edges[0].target.modifiers) != specificity:
                continue
            resolved_vals: list[tuple[float, Any, str]] = []
            consumed: set[str] = set()
            for edge in group_edges:
                value, identifier = self._resolve_atom_value(
                    edge.source,
                    facts,
                    calculation_arcs,
                    visited=_visited,
                    excluded=frozenset(consumed),
                    preferred=child_qnames,
                )
                if value is None or identifier is None:
                    break
                resolved_vals.append((value, edge, identifier))
                if identifier in fact_qnames:
                    consumed.add(identifier)

            if len(resolved_vals) != len(group_edges) or not resolved_vals:
                continue
            outcome = self._verify_non_double_counting(
                [identifier for _, _, identifier in resolved_vals],
                calculation_arcs,
            )
            components = tuple(
                GranularComponent(
                    identifier=identifier,
                    value=value,
                    weight=edge.algebraic_weight,
                )
                for value, edge, identifier in resolved_vals
            )
            canonical_hops = sum(
                1 for _, _, identifier in resolved_vals if identifier not in fact_qnames
            )
            total = sum(
                value * edge.algebraic_weight for value, edge, _ in resolved_vals
            )
            path = tuple(
                f"{edge.source}({value}) * {edge.algebraic_weight}"
                for value, edge, _ in resolved_vals
            )
            attempts.append((canonical_hops, outcome, components, total, path))

        attempts.extend(
            self._inverse_attempts(
                target_atom,
                target_concept,
                complete_groups,
                facts,
                calculation_arcs,
                _visited,
                fact_qnames,
            )
        )
        attempts.sort(key=lambda attempt: attempt[0])
        for _, outcome, components, total, path in attempts:
            if outcome.violations:
                continue
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
        if attempts:
            _, outcome, components, _, _ = attempts[0]
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
        return None

    def _inverse_attempts(
        self,
        target_atom: Any,
        target_concept: str,
        complete_groups: list[tuple[str, list[Any]]],
        facts: Sequence[XbrlFact],
        calculation_arcs: Sequence[CalculationArc],
        visited: set[str] | None,
        fact_qnames: set[str],
    ) -> list[tuple[int, Any, tuple, float, tuple[str, ...]]]:
        """Solve complete formulas for the target term: the term is
        (total - the other terms' weighted sum) / its weight, with the
        total and the other terms resolved from filed facts.
        """
        candidates: list[tuple[int, str, list[Any], Any]] = []
        for key, group_edges in complete_groups:
            if target_atom.is_a(group_edges[0].target):
                continue
            matched = [edge for edge in group_edges if target_atom.is_a(edge.source)]
            if len(matched) == 1 and matched[0].algebraic_weight != 0:
                candidates.append(
                    (len(matched[0].source.modifiers), key, group_edges, matched[0])
                )
        specificity = max((row[0] for row in candidates), default=-1)
        attempts: list[tuple[int, Any, tuple, float, tuple[str, ...]]] = []
        for _, key, group_edges, target_edge in candidates:
            if len(target_edge.source.modifiers) != specificity:
                continue
            total_atom = group_edges[0].target
            total_value, total_id = self._resolve_atom_value(
                total_atom,
                facts,
                calculation_arcs,
                visited=visited,
            )
            if total_value is None or total_id is None:
                continue
            if total_id not in fact_qnames:
                # The total must be a filed fact, not a sub-derivation:
                # solving from a derived total is circular.
                continue
            # A total carried by a fact with the target's own atom is
            # the target quantity itself (or a sibling of it): solving
            # the formula "for the target" from it is circular.
            total_fact_atom, _, _, _ = self.kb.decomposition(total_id)
            if total_fact_atom == target_atom:
                continue
            if not any(
                arc.parent_qname == total_id and arc.child_qname == target_concept
                for arc in calculation_arcs
            ):
                # The filer's own calculation structure must place the
                # target concept as a term of the total concept; an atom
                # resemblance alone does not make it the formula's term.
                continue
            consumed = {total_id} if total_id in fact_qnames else set()
            total_children = frozenset(
                arc.child_qname
                for arc in calculation_arcs
                if arc.parent_qname == total_id
            )
            resolved_others: list[tuple[float, Any, str]] = []
            for edge in group_edges:
                if edge is target_edge:
                    continue
                value, identifier = self._resolve_atom_value(
                    edge.source,
                    facts,
                    calculation_arcs,
                    visited=visited,
                    excluded=frozenset(consumed),
                    preferred=total_children,
                )
                if value is None or identifier is None:
                    resolved_others = []
                    break
                resolved_others.append((value, edge, identifier))
                if identifier in fact_qnames:
                    consumed.add(identifier)
            if len(resolved_others) != len(group_edges) - 1:
                continue
            identifiers = [total_id] + [
                identifier for _, _, identifier in resolved_others
            ]
            # Only the summed terms are double-counting-checked: the
            # total stands in the formula's own relation to them (its
            # calc expression contains them), which is the equation
            # being solved, not an overlap.
            outcome = self._verify_non_double_counting(
                [identifier for _, _, identifier in resolved_others],
                calculation_arcs,
            )
            components = (
                GranularComponent(identifier=total_id, value=total_value, weight=1.0),
            ) + tuple(
                GranularComponent(
                    identifier=identifier,
                    value=value,
                    weight=edge.algebraic_weight,
                )
                for value, edge, identifier in resolved_others
            )
            canonical_hops = sum(
                1 for identifier in identifiers if identifier not in fact_qnames
            )
            solved = (
                total_value
                - sum(
                    value * edge.algebraic_weight for value, edge, _ in resolved_others
                )
            ) / target_edge.algebraic_weight
            path = (f"solved:{key} for {target_edge.source}",) + tuple(
                f"{atom}({value}) * {weight}"
                for atom, value, weight in [
                    (total_atom, total_value, 1.0),
                    *[
                        (edge.source, value, edge.algebraic_weight)
                        for value, edge, _ in resolved_others
                    ],
                ]
            )
            attempts.append((canonical_hops, outcome, components, solved, path))
        return attempts

    def _derive_eps(
        self,
        target_atom: Any,
        facts: Sequence[XbrlFact],
        *,
        measure_id: str,
        entity: str,
        period: str,
        unit: str,
    ) -> AggregateFact | None:
        """Derive an EPS value from its filed legs via the EPS identity.

        Both legs must be filed with a single value in scope; the
        route abstains otherwise rather than substituting a leg.
        """
        diluted = eps_diluted(target_atom)
        if diluted is None:
            return None
        legs = eps_identity_legs(facts, diluted=diluted)
        if legs is None:
            return None
        numerator_qname = legs.numerator_facts[0].concept_qname
        shares_qname = legs.shares_facts[0].concept_qname
        return AggregateFact(
            measure_id=measure_id,
            entity=entity,
            period=period,
            unit=unit,
            value=round(legs.numerator_value / legs.shares_value, 4),
            basis="DERIVED_EXACT",
            components=(
                GranularComponent(
                    identifier=numerator_qname,
                    value=legs.numerator_value,
                    weight=1.0,
                ),
            ),
            derivation_path=(
                f"{numerator_qname}({legs.numerator_value}) / "
                f"{shares_qname}({legs.shares_value})",
            ),
            resolution_tier="ACCOUNTING_IDENTITY",
        )

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

        target_local = qname_local(target_concept)
        fact_vals = {
            fact.concept_qname: float(fact.value)
            for fact in facts
            if not fact.dimensions and isinstance(fact.value, (int, float))
        }
        local_fact_vals = {
            qname_local(fact.concept_qname): float(fact.value)
            for fact in facts
            if not fact.dimensions and isinstance(fact.value, (int, float))
        }

        direct_val = fact_vals.get(target_concept, local_fact_vals.get(target_local))
        resolved_concept = target_concept
        if direct_val is None:
            for candidate in self.kb.taxonomy.equivalent_concepts(target_local):
                candidate_val = fact_vals.get(
                    candidate, local_fact_vals.get(qname_local(candidate))
                )
                if candidate_val is not None:
                    direct_val = candidate_val
                    resolved_concept = candidate
                    break

        lexicon = self.kb.taxonomy.token_lexicon
        if direct_val is None and lexicon is not None:
            target_atom, _, _, _ = self.kb.decomposition(target_concept)
            for fact in facts:
                if fact.dimensions or not isinstance(fact.value, (int, float)):
                    continue
                fact_atom, _, _, _ = self.kb.decomposition(fact.concept_qname)
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
            or qname_local(arc.parent_qname) == target_local
        ]
        if child_arcs:
            nil_children = {
                fact.concept_qname
                for fact in facts
                if not fact.dimensions and not isinstance(fact.value, (int, float))
            }
            nil_local = {qname_local(qname) for qname in nil_children}
            total = 0.0
            path: list[str] = []
            all_resolved = True
            for arc in child_arcs:
                value = fact_vals.get(
                    arc.child_qname,
                    local_fact_vals.get(qname_local(arc.child_qname)),
                )
                if value is None:
                    # A nil-reported child contributes nothing, as in
                    # breakdown_concept; an absent child still blocks.
                    if (
                        arc.child_qname in nil_children
                        or qname_local(arc.child_qname) in nil_local
                    ):
                        continue
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

        if lexicon is not None:
            target_atom, _, _, _ = self.kb.decomposition(target_concept)
            derived = self._derive_atom(
                target_atom,
                facts,
                calculation_arcs,
                _visited,
                measure_id=target_concept,
                entity=entity,
                period=period,
                unit=unit,
            )
            if derived is not None:
                return derived
            eps = self._derive_eps(
                target_atom,
                facts,
                measure_id=target_concept,
                entity=entity,
                period=period,
                unit=unit,
            )
            if eps is not None:
                return eps

        return AggregateFact(
            measure_id=target_concept,
            entity=entity,
            period=period,
            unit=unit,
            value=None,
            basis="NOT_AVAILABLE",
            resolution_tier="UNRESOLVED",
        )
