"""Dimensional and slice consumption passes of the counter-solver."""

from __future__ import annotations

from collections.abc import Sequence

from edgar_sec.engine.xbrl.schema.models import CalculationArc, XbrlFact
from edgar_sec.engine.xbrl.solve.evaluation.counter_keys import (
    _ContextKey,
    _FinerIndex,
    _Resolution,
    _SemanticKey,
    _context_key,
    _local_name,
    _precision_tolerance,
)


class ConsumptionMixin:
    """Computes the semantic keys consumed by balanced fact groups."""

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
