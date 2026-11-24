"""Typed residual-component hypotheses over the counter-solver partition."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from edgar_sec.engine.xbrl.schema.models import (
    CalculationArc,
    ConceptDeclaration,
    XbrlFact,
)
from edgar_sec.engine.xbrl.solve.concepts.equivalence import (
    UNRELATED,
    classify_ladder_pair,
)
from edgar_sec.engine.xbrl.solve.concepts.tokenizer import ConceptTokenizer
from edgar_sec.engine.xbrl.solve.core.breakdown import (
    PeriodKey,
    breakdown_concept,
    period_key_of,
)
from edgar_sec.engine.xbrl.solve.evaluation.counter_keys import _local_name
from edgar_sec.engine.xbrl.solve.evaluation.counter_quarantine import QuarantinedFact
from edgar_sec.engine.xbrl.taxonomy.archive import current_table
from edgar_sec.engine.xbrl.taxonomy.item_types import declaration_for, item_type_local


@dataclass(frozen=True, slots=True)
class AuditHypothesis:
    """A typed residual-component hypothesis closing one goal period."""

    concept_qname: str
    hypothesized_parent: str
    algebraic_weight: float
    hypothesis_type: str
    residual_delta: float
    period: str = ""


def _period_label(key: PeriodKey) -> str:
    _period_type, instant, start, end = key
    if instant:
        return instant
    if end:
        return end
    if start:
        return f"{start}/{end or ''}"
    return ""


class TypedHypothesesMixin:
    """Generates typed residual-component hypotheses over the partition."""

    def _typed_hypotheses(
        self,
        facts: Sequence[XbrlFact],
        target_goals: Sequence[str],
        calculation_arcs: Sequence[CalculationArc],
        quarantined: Sequence[QuarantinedFact],
        declarations: Mapping[str, ConceptDeclaration] | None,
    ) -> list[AuditHypothesis]:
        """Typed residual-component hypotheses over the final partition.

        Residuals are recomputed per (goal, period) via breakdown_concept;
        a source emits only when every typed eligibility rule admits it.
        """
        kb = getattr(self.primary_solver, "kb", None)
        if kb is None or not target_goals or not quarantined:
            return []
        taxonomy = kb.taxonomy
        table = current_table()
        supplied = declarations or {}

        def effective(qname: str) -> ConceptDeclaration | None:
            return declaration_for(qname, table, supplied)

        def is_monetary(qname: str) -> bool:
            declaration = effective(qname)
            return (
                declaration is not None
                and item_type_local(declaration.item_type) == "monetaryItemType"
            )

        children: dict[str, set[str]] = {}
        for arc in calculation_arcs:
            children.setdefault(arc.parent_qname, set()).add(arc.child_qname)
        desc_cache: dict[str, frozenset[str]] = {}

        def descendants(start: str) -> frozenset[str]:
            if start not in desc_cache:
                roots = (
                    [start]
                    if start in children
                    else [p for p in children if _local_name(p) == _local_name(start)]
                )
                seen: set[str] = set()
                stack = [child for root in roots for child in children.get(root, ())]
                while stack:
                    node = stack.pop()
                    if node not in seen:
                        seen.add(node)
                        stack.extend(children.get(node, ()))
                desc_cache[start] = frozenset(seen)
            return desc_cache[start]

        def in_subtree(member: str, root: str) -> bool:
            subtree = descendants(root)
            return member in subtree or any(
                _local_name(member) == _local_name(node) for node in subtree
            )

        tokenizer: ConceptTokenizer | None = None
        atom_cache: dict[str, Any] = {}

        def ladder_unrelated(target: str, source: str) -> bool:
            nonlocal tokenizer
            if tokenizer is None:
                tokenizer = ConceptTokenizer(taxonomy)
            for qname in (target, source):
                if qname not in atom_cache:
                    atom_cache[qname] = tokenizer.tokenize(qname, effective(qname)).atom
            result = classify_ladder_pair(
                atom_cache[target],
                atom_cache[source],
                taxonomy.default_coordinates,
                sibling_groups=taxonomy.sibling_groups or None,
                same_qname=target == source,
            )
            return result.tier == UNRELATED

        goals_by_local: dict[str, list[str]] = {}
        for goal in target_goals:
            goals_by_local.setdefault(_local_name(goal), []).append(goal)
        reported_by_goal: dict[str, dict[PeriodKey, list[XbrlFact]]] = {}
        for fact in facts:
            if fact.dimensions or not isinstance(fact.value, (int, float)):
                continue
            for goal in goals_by_local.get(_local_name(fact.concept_qname), []):
                reported_by_goal.setdefault(goal, {}).setdefault(
                    period_key_of(fact), []
                ).append(fact)

        sources_by_period: dict[PeriodKey, dict[str, list[XbrlFact]]] = {}
        for entry in quarantined:
            fact = entry.fact
            if fact.dimensions or not isinstance(fact.value, (int, float)):
                continue
            sources_by_period.setdefault(period_key_of(fact), {}).setdefault(
                fact.concept_qname, []
            ).append(fact)

        facts_by_period: dict[PeriodKey, list[XbrlFact]] = {}
        for fact in facts:
            facts_by_period.setdefault(period_key_of(fact), []).append(fact)

        closers: list[tuple[str, PeriodKey, str, float, float]] = []
        for goal in target_goals:
            if not is_monetary(goal):
                continue
            for period_key, target_facts in sorted(
                reported_by_goal.get(goal, {}).items(), key=lambda item: str(item[0])
            ):
                if len({float(fact.value) for fact in target_facts}) != 1:
                    continue
                period_facts = facts_by_period.get(period_key, [])
                breakdown = breakdown_concept(
                    kb, goal, period_facts, calculation_arcs, period_key=period_key
                )
                if breakdown.total_value is None or not breakdown.components:
                    continue
                residual = breakdown.signed_discrepancy
                if abs(residual) < 1.0:
                    continue
                target_unit = taxonomy.normalize_unit(target_facts[0].unit)
                for source, source_facts in sources_by_period.get(
                    period_key, {}
                ).items():
                    if source == goal or _local_name(source) == _local_name(goal):
                        continue
                    if len({float(fact.value) for fact in source_facts}) != 1:
                        continue
                    value = float(source_facts[0].value)
                    if value == 0.0:
                        continue
                    if taxonomy.normalize_unit(source_facts[0].unit) != target_unit:
                        continue
                    if not is_monetary(source):
                        continue
                    if in_subtree(source, goal) or in_subtree(goal, source):
                        continue
                    weights = [
                        weight
                        for weight in (1.0, -1.0)
                        if abs(residual - weight * value) < 1.0
                    ]
                    if len(weights) != 1:
                        continue
                    if ladder_unrelated(goal, source):
                        continue
                    closers.append(
                        (
                            goal,
                            period_key,
                            source,
                            weights[0],
                            abs(residual - weights[0] * value),
                        )
                    )

        per_goal_period = Counter((goal, key) for goal, key, *_ in closers)
        per_source = Counter(source for *_head, source, _w, _d in closers)
        hypotheses: list[AuditHypothesis] = []
        emitted: set[tuple[str, str]] = set()
        for goal, period_key, source, weight, delta in sorted(
            closers, key=lambda closer: (closer[0], closer[2], str(closer[1]))
        ):
            if per_goal_period[(goal, period_key)] > 1 or per_source[source] > 1:
                continue
            if (source, goal) in emitted:
                continue
            emitted.add((source, goal))
            hypotheses.append(
                AuditHypothesis(
                    concept_qname=source,
                    hypothesized_parent=goal,
                    algebraic_weight=weight,
                    hypothesis_type="RESIDUAL_COMPONENT",
                    residual_delta=delta,
                    period=_period_label(period_key),
                )
            )
        return hypotheses
