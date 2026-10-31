"""Counter-solver implementing Epistemic Quarantine and Conservation of Facts."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from edgar_sec.engine.xbrl.evidence.evidence import UnificationRule
from edgar_sec.engine.xbrl.schema.models import (
    AggregateFact,
    CalculationArc,
    ConceptDeclaration,
    XbrlFact,
    qname_local,
)
from edgar_sec.engine.xbrl.solve.breakdown import (
    PeriodKey,
    breakdown_concept,
    period_key_of,
)
from edgar_sec.engine.xbrl.solve.equivalence import UNRELATED, classify_ladder_pair
from edgar_sec.engine.xbrl.solve.solver import XbrlConstraintSolver
from edgar_sec.engine.xbrl.solve.tokenizer import ConceptTokenizer
from edgar_sec.engine.xbrl.taxonomy.archive import current_table
from edgar_sec.engine.xbrl.taxonomy.item_types import declaration_for, item_type_local

_ContextKey = tuple[object, ...]
_SemanticKey = tuple[str, _ContextKey, float]
_Resolution = tuple[float, frozenset[_SemanticKey], bool, float]
_FinerEntry = tuple[str, _ContextKey, float, frozenset]
_FinerIndex = dict[_ContextKey, list[_FinerEntry]]


def _precision_tolerance(fact: XbrlFact) -> float:
    """Half the fact's last filed digit; a missing decimals gets the flat floor."""
    if fact.decimals is None:
        return 0.0001
    return 0.5 * (10.0 ** (-fact.decimals))


# Quarantine reasons are pair-level: exact-qname calc membership plus the
# unconsumed remainder's shape; partially consumed covers fact-level passes.
REASON_DIMENSIONED_ONLY_NO_CALC_ROLE = "DIMENSIONED_ONLY_NO_CALC_ROLE"
REASON_DIMENSIONED_ONLY_IN_CALC_ARCS = "DIMENSIONED_ONLY_IN_CALC_ARCS"
REASON_DIMENSIONED_ONLY_IN_CALC_ARCS_PARTIALLY_CONSUMED = (
    "DIMENSIONED_ONLY_IN_CALC_ARCS_PARTIALLY_CONSUMED"
)
REASON_UNDIMENSIONED_NO_CALC_ROLE = "UNDIMENSIONED_NO_CALC_ROLE"
REASON_UNDIMENSIONED_IN_CALC_ARCS_NOT_CONSUMED = (
    "UNDIMENSIONED_IN_CALC_ARCS_NOT_CONSUMED"
)
REASON_UNDIMENSIONED_IN_CALC_ARCS_PARENT_NOT_AUDITED = (
    "UNDIMENSIONED_IN_CALC_ARCS_PARENT_NOT_AUDITED"
)
QUARANTINE_REASONS = (
    REASON_DIMENSIONED_ONLY_NO_CALC_ROLE,
    REASON_DIMENSIONED_ONLY_IN_CALC_ARCS,
    REASON_DIMENSIONED_ONLY_IN_CALC_ARCS_PARTIALLY_CONSUMED,
    REASON_UNDIMENSIONED_NO_CALC_ROLE,
    REASON_UNDIMENSIONED_IN_CALC_ARCS_NOT_CONSUMED,
    REASON_UNDIMENSIONED_IN_CALC_ARCS_PARENT_NOT_AUDITED,
)


def _context_key(fact: XbrlFact) -> _ContextKey:
    return (
        str(fact.accession),
        fact.period_type,
        fact.instant_date,
        fact.start_date,
        fact.end_date,
        fact.unit,
        tuple(sorted(fact.dimensions.items())),
    )


def _semantic_key(fact: XbrlFact) -> _SemanticKey:
    return (fact.concept_qname, _context_key(fact), float(fact.value))


def _local_name(qname: str) -> str:
    return qname_local(qname)


@dataclass(frozen=True, slots=True)
class QuarantinedFact:
    """An unconsumed filing fact captured in Epistemic Quarantine."""

    fact: XbrlFact
    reason: str


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


@dataclass(frozen=True, slots=True)
class CounterSolverOutcome:
    """Complete accounting partition of filing facts and induced hypotheses."""

    solved_facts: tuple[XbrlFact, ...]
    rejected_facts: tuple[XbrlFact, ...]
    quarantined_facts: tuple[QuarantinedFact, ...]
    hypotheses: tuple[AuditHypothesis, ...]


class CounterSolver:
    """Audits unseen facts against residuals to discover unmapped components."""

    def __init__(self, primary_solver: XbrlConstraintSolver) -> None:
        """Initialize CounterSolver wrapping a primary constraint solver."""
        self.primary_solver = primary_solver

    @staticmethod
    def evaluate_rule_weight(
        rule: UnificationRule,
        firm: str,
        sector: str,
        year: int | str = "*",
    ) -> float:
        """Calculate scope-adjusted rule weight with cross-firm prior discounting."""
        s_firm, s_sec, _ = rule.scope
        if s_firm == firm:
            return rule.weight
        if s_firm == "*":
            if s_sec in ("*", sector):
                return rule.weight
            return 0.0
        # Rule belongs to another firm: discount if same sector
        if s_sec in ("*", sector):
            return rule.weight * 0.5
        return 0.0

    def _finer_aggregate(
        self,
        concept: str,
        context: _ContextKey,
        *,
        tolerances: dict[tuple[str, _ContextKey], float],
        finer: _FinerIndex,
        finer_ambiguous: frozenset[tuple[str, _ContextKey, tuple[str, ...]]],
    ) -> _Resolution | None:
        """Aggregate a concept's finer-context facts to a coarser context.

        Groups share one axis set extending the context's dimensions and
        must all agree, so competing breakdowns cannot both be spent.
        """
        coordinate = context[:6]
        base = set(context[-1])
        entries = [entry for entry in finer.get(coordinate, ()) if entry[3] > base]
        qname = concept if any(entry[0] == concept for entry in entries) else None
        if qname is None:
            local = {
                entry[0]
                for entry in entries
                if _local_name(entry[0]) == _local_name(concept)
            }
            qname = next(iter(local)) if len(local) == 1 else None
        if qname is None:
            return None
        groups: dict[tuple[str, ...], list[_FinerEntry]] = {}
        for entry in entries:
            if entry[0] != qname:
                continue
            axes = tuple(axis for axis, _member in entry[1][-1])
            if (qname, coordinate, axes) in finer_ambiguous:
                return None
            groups.setdefault(axes, []).append(entry)
        if not groups:
            return None
        totals: list[tuple[float, float, frozenset[_SemanticKey]]] = []
        for members in groups.values():
            totals.append(
                (
                    sum(entry[2] for entry in members),
                    sum(
                        tolerances.get((entry[0], entry[1]), 0.0001)
                        for entry in members
                    ),
                    frozenset((entry[0], entry[1], entry[2]) for entry in members),
                )
            )
        value, spread, _keys = totals[0]
        consumed: set[_SemanticKey] = set()
        for total, group_spread, keys in totals:
            if abs(total - value) > spread + group_spread:
                return None
            spread = max(spread, group_spread + abs(total - value))
            consumed |= keys
        return (value, frozenset(consumed), True, spread)

    def _resolve_dimensional(
        self,
        concept: str,
        context: _ContextKey,
        *,
        values: dict[tuple[str, _ContextKey], float | None],
        tolerances: dict[tuple[str, _ContextKey], float],
        qname_by_local: dict[tuple[str, _ContextKey], str],
        arcs_by_parent: dict[str, tuple[CalculationArc, ...]],
        arcs_by_local: dict[str, tuple[CalculationArc, ...]],
        finer: _FinerIndex,
        finer_ambiguous: frozenset[tuple[str, _ContextKey, tuple[str, ...]]],
        visited: frozenset[str],
    ) -> _Resolution | None:
        """Resolve one concept in one exact context from calc arcs alone.

        Atom-fallback tiers never apply here; sums agree with a reported
        value within the accumulated filed precision (half last digit).
        """
        if concept in visited:
            return None
        qname = concept if (concept, context) in values else None
        if qname is None:
            qname = qname_by_local.get((_local_name(concept), context))
        reported = values.get((qname, context)) if qname is not None else None
        if qname is not None and (qname, context) in values and reported is None:
            return None
        own: frozenset[_SemanticKey] = (
            frozenset({(qname, context, reported)})
            if qname is not None and reported is not None
            else frozenset()
        )
        own_tolerance = (
            tolerances.get((qname, context), 0.0001) if qname is not None else 0.0
        )
        child_arcs = (
            arcs_by_parent.get(concept)
            or arcs_by_parent.get(qname or "", ())
            or arcs_by_local.get(_local_name(concept), ())
        )
        if not child_arcs:
            if reported is not None:
                return (reported, own, True, own_tolerance)
            return self._finer_aggregate(
                concept,
                context,
                tolerances=tolerances,
                finer=finer,
                finer_ambiguous=finer_ambiguous,
            )
        total = 0.0
        spread = 0.0
        consumed: set[_SemanticKey] = set()
        for arc in child_arcs:
            resolved = self._resolve_dimensional(
                arc.child_qname,
                context,
                values=values,
                tolerances=tolerances,
                qname_by_local=qname_by_local,
                arcs_by_parent=arcs_by_parent,
                arcs_by_local=arcs_by_local,
                finer=finer,
                finer_ambiguous=finer_ambiguous,
                visited=visited | {concept},
            )
            if resolved is None:
                break
            total += resolved[0] * arc.weight
            spread += abs(arc.weight) * resolved[3]
            consumed |= resolved[1]
        else:
            if reported is None:
                return (round(total, 4), frozenset(consumed), True, spread)
            if abs(total - reported) <= own_tolerance + spread:
                return (reported, own | consumed, True, own_tolerance)
            return (reported, own, False, own_tolerance)
        if reported is not None:
            return (reported, own, False, own_tolerance)
        return self._finer_aggregate(
            concept,
            context,
            tolerances=tolerances,
            finer=finer,
            finer_ambiguous=finer_ambiguous,
        )

    def _dimensional_consumed_keys(
        self,
        facts: Sequence[XbrlFact],
        targets: Sequence[str],
        calculation_arcs: Sequence[CalculationArc],
    ) -> set[_SemanticKey]:
        """Semantic keys consumed by balanced exact contexts of targets."""
        distinct: dict[tuple[str, _ContextKey], set[float]] = {}
        finest: dict[tuple[str, _ContextKey], float] = {}
        for fact in facts:
            if isinstance(fact.value, (int, float)):
                key = (fact.concept_qname, _context_key(fact))
                distinct.setdefault(key, set()).add(float(fact.value))
                tolerance = _precision_tolerance(fact)
                if key not in finest or tolerance < finest[key]:
                    finest[key] = tolerance
        values: dict[tuple[str, _ContextKey], float | None] = {
            key: next(iter(found)) if len(found) == 1 else None
            for key, found in distinct.items()
        }
        local_candidates: dict[tuple[str, _ContextKey], set[str]] = {}
        for qname, context in distinct:
            local_candidates.setdefault((_local_name(qname), context), set()).add(qname)
        qname_by_local = {
            key: next(iter(found))
            for key, found in local_candidates.items()
            if len(found) == 1
        }
        arcs_by_parent: dict[str, list[CalculationArc]] = {}
        for arc in calculation_arcs:
            arcs_by_parent.setdefault(arc.parent_qname, []).append(arc)
        grouped = {name: tuple(arcs) for name, arcs in arcs_by_parent.items()}
        local_parents: dict[str, set[str]] = {}
        for parent in grouped:
            local_parents.setdefault(_local_name(parent), set()).add(parent)
        arcs_by_local = {
            local: grouped[next(iter(parents))]
            for local, parents in local_parents.items()
            if len(parents) == 1
        }
        finer: _FinerIndex = {}
        ambiguous: set[tuple[str, _ContextKey, tuple[str, ...]]] = set()
        for (qname, context), found in distinct.items():
            coordinate = context[:6]
            axes = tuple(axis for axis, _member in context[-1])
            if len(found) != 1:
                ambiguous.add((qname, coordinate, axes))
                continue
            finer.setdefault(coordinate, []).append(
                (qname, context, next(iter(found)), frozenset(context[-1]))
            )
        finer_ambiguous = frozenset(ambiguous)

        contexts_by_qname: dict[str, set[_ContextKey]] = {}
        contexts_by_local: dict[str, set[_ContextKey]] = {}
        for (qname, context), value in values.items():
            if not context[-1] or value is None:
                continue
            contexts_by_qname.setdefault(qname, set()).add(context)
            contexts_by_local.setdefault(_local_name(qname), set()).add(context)

        consumed: set[_SemanticKey] = set()
        for target in targets:
            target_local = _local_name(target)
            if target not in grouped and target_local not in arcs_by_local:
                continue
            contexts = contexts_by_qname.get(target, set()) | contexts_by_local.get(
                target_local, set()
            )
            for context in contexts:
                resolved = self._resolve_dimensional(
                    target,
                    context,
                    values=values,
                    tolerances=finest,
                    qname_by_local=qname_by_local,
                    arcs_by_parent=grouped,
                    arcs_by_local=arcs_by_local,
                    finer=finer,
                    finer_ambiguous=finer_ambiguous,
                    visited=frozenset(),
                )
                if resolved is not None and resolved[2]:
                    consumed |= resolved[1]
        return consumed

    def _slice_consumed_keys(
        self,
        facts: Sequence[XbrlFact],
        targets: Sequence[str],
    ) -> set[_SemanticKey]:
        """Semantic keys of slice groups balancing a reported total.

        A group is one axis set at one (unit, period) coordinate, duplicates
        collapsed, summed against the undimensioned value at that coordinate.
        """
        wanted = set(targets)
        anchors: dict[tuple[str, _ContextKey], set[float]] = {}
        anchor_tolerances: dict[tuple[str, _ContextKey], float] = {}
        collapsed: dict[tuple[str, _ContextKey], set[float]] = {}
        member_tolerances: dict[_SemanticKey, float] = {}
        for fact in facts:
            if fact.concept_qname not in wanted or not isinstance(
                fact.value, (int, float)
            ):
                continue
            coordinate = _context_key(fact)[:6]
            tolerance = _precision_tolerance(fact)
            if fact.dimensions:
                key = (fact.concept_qname, _context_key(fact))
                collapsed.setdefault(key, set()).add(float(fact.value))
                member_key = (fact.concept_qname, _context_key(fact), float(fact.value))
                if (
                    member_key not in member_tolerances
                    or tolerance < member_tolerances[member_key]
                ):
                    member_tolerances[member_key] = tolerance
            else:
                anchor_key = (fact.concept_qname, coordinate)
                anchors.setdefault(anchor_key, set()).add(float(fact.value))
                if (
                    anchor_key not in anchor_tolerances
                    or tolerance < anchor_tolerances[anchor_key]
                ):
                    anchor_tolerances[anchor_key] = tolerance
        groups: dict[
            tuple[str, _ContextKey, tuple[str, ...]], dict[_SemanticKey, float]
        ] = {}
        for (qname, context), found in collapsed.items():
            if len(found) != 1:
                continue
            axes = tuple(axis for axis, _member in context[-1])
            group_key = (qname, context[:6], axes)
            groups.setdefault(group_key, {})[(qname, context, next(iter(found)))] = (
                next(iter(found))
            )
        consumed: set[_SemanticKey] = set()
        for (qname, coordinate, _axes), members in groups.items():
            anchor = anchors.get((qname, coordinate), set())
            if len(anchor) != 1:
                continue
            anchor_value = next(iter(anchor))
            spread = anchor_tolerances.get((qname, coordinate), 0.0001) + sum(
                member_tolerances.get(key, 0.0001) for key in members
            )
            if abs(sum(members.values()) - anchor_value) <= spread:
                consumed |= set(members)
                consumed.add((qname, coordinate + ((),), anchor_value))
        return consumed

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

    @staticmethod
    def _pair_reasons(
        solved: Sequence[XbrlFact],
        unconsumed: Sequence[XbrlFact],
        calculation_arcs: Sequence[CalculationArc],
        audited: frozenset[str],
    ) -> dict[str, str]:
        """Pair reason per quarantined concept from arcs and fact shape."""
        in_arcs: set[str] = set()
        parents: dict[str, set[str]] = {}
        for arc in calculation_arcs:
            in_arcs.add(arc.parent_qname)
            in_arcs.add(arc.child_qname)
            parents.setdefault(arc.child_qname, set()).add(arc.parent_qname)
        consumed = Counter(
            fact.concept_qname
            for fact in solved
            if isinstance(fact.value, (int, float))
        )
        grouped: dict[str, list[XbrlFact]] = {}
        for fact in unconsumed:
            grouped.setdefault(fact.concept_qname, []).append(fact)
        reasons: dict[str, str] = {}
        for concept, members in grouped.items():
            if all(fact.dimensions for fact in members):
                if concept not in in_arcs:
                    reasons[concept] = REASON_DIMENSIONED_ONLY_NO_CALC_ROLE
                elif consumed[concept]:
                    reasons[concept] = (
                        REASON_DIMENSIONED_ONLY_IN_CALC_ARCS_PARTIALLY_CONSUMED
                    )
                else:
                    reasons[concept] = REASON_DIMENSIONED_ONLY_IN_CALC_ARCS
                continue
            if concept not in in_arcs:
                reasons[concept] = REASON_UNDIMENSIONED_NO_CALC_ROLE
            elif (
                parents.get(concept)
                and not parents[concept] & audited
                and concept not in audited
            ):
                reasons[concept] = REASON_UNDIMENSIONED_IN_CALC_ARCS_PARENT_NOT_AUDITED
            else:
                reasons[concept] = REASON_UNDIMENSIONED_IN_CALC_ARCS_NOT_CONSUMED
        return reasons

    def audit_filing(
        self,
        facts: Sequence[XbrlFact],
        target_goals: Sequence[str],
        calculation_arcs: Sequence[CalculationArc] = (),
        *,
        dimensional_target_goals: Sequence[str] = (),
        anchored_target_goals: Sequence[str] = (),
        declarations: Mapping[str, ConceptDeclaration] | None = None,
    ) -> CounterSolverOutcome:
        """Audit filing facts against goals enforcing Conservation of Facts."""
        solved_qnames: set[str] = set()
        dimensional_consumed = self._dimensional_consumed_keys(
            facts, dimensional_target_goals, calculation_arcs
        )
        dimensional_consumed |= self._dimensional_consumed_keys(
            facts, anchored_target_goals, calculation_arcs
        )
        dimensional_consumed |= self._slice_consumed_keys(facts, anchored_target_goals)

        # 1. Execute primary solver over target goals
        for goal in target_goals:
            agg: AggregateFact = self.primary_solver.evaluate_goal(
                goal, facts, calculation_arcs
            )
            if agg.value is not None:
                solved_qnames.add(goal)
                if agg.breakdown is not None:
                    for comp in agg.breakdown.components:
                        solved_qnames.add(comp.identifier)
                if agg.components:
                    for comp in agg.components:
                        solved_qnames.add(comp.identifier)

        # 2. Partition facts into solved, rejected, and quarantined
        solved: list[XbrlFact] = []
        rejected: list[XbrlFact] = []
        unconsumed: list[XbrlFact] = []
        containment: dict[str, bool] = {}

        for f in facts:
            q_loc = qname_local(f.concept_qname)
            if (
                isinstance(f.value, (int, float))
                and _semantic_key(f) in dimensional_consumed
            ):
                solved.append(f)
            elif (
                f.concept_qname in solved_qnames
                or q_loc in solved_qnames
                or containment.setdefault(q_loc, any(q_loc in s for s in solved_qnames))
            ):
                solved.append(f)
            elif f.value is None or not isinstance(f.value, (int, float)):
                rejected.append(f)
            else:
                unconsumed.append(f)

        audited = (
            frozenset(target_goals)
            | frozenset(dimensional_target_goals)
            | frozenset(anchored_target_goals)
        )
        reasons = self._pair_reasons(solved, unconsumed, calculation_arcs, audited)
        quarantined = [
            QuarantinedFact(fact=f, reason=reasons[f.concept_qname]) for f in unconsumed
        ]

        # 3. Typed hypothesis generation over the final partition
        hypotheses = self._typed_hypotheses(
            facts, target_goals, calculation_arcs, quarantined, declarations
        )

        return CounterSolverOutcome(
            solved_facts=tuple(solved),
            rejected_facts=tuple(rejected),
            quarantined_facts=tuple(quarantined),
            hypotheses=tuple(hypotheses),
        )
