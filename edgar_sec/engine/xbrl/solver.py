"""Constraint-satisfaction graph solver and multi-hop financial derivation engine."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from edgar_sec.engine.xbrl.decomposer import infer_semantic_frame
from edgar_sec.engine.xbrl.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.gold import PlacementPrediction
from edgar_sec.engine.xbrl.models import (
    CalculationArc,
    PresentationArc,
    XbrlFact,
)


@dataclass(frozen=True, slots=True)
class SolvedGoal:
    """Evaluated financial target value with provenance and derivation path."""

    target_concept: str
    computed_value: float | None
    resolution_tier: str
    derivation_path: tuple[str, ...] = ()
    confidence: float = 1.0
    is_direct: bool = False


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

            # 3. Subatomic prime head induction
            if self.enable_head_induction:
                frame = infer_semantic_frame(
                    qname,
                    self.kb.taxonomy,
                    unit=fact.unit,
                    balance=fact.balance,
                )
                if frame.prime_head == "H_REVENUE":
                    predictions.append(
                        PlacementPrediction(
                            concept_qname=qname,
                            predicted_parent="us-gaap:GrossProfit",
                            predicted_weight=1.0,
                        )
                    )
                    continue
                if frame.prime_head == "H_COST":
                    predictions.append(
                        PlacementPrediction(
                            concept_qname=qname,
                            predicted_parent="us-gaap:GrossProfit",
                            predicted_weight=-1.0,
                        )
                    )
                    continue
                if frame.prime_head == "H_EXPENSE":
                    predictions.append(
                        PlacementPrediction(
                            concept_qname=qname,
                            predicted_parent="us-gaap:OperatingIncomeLoss",
                            predicted_weight=-1.0,
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

    def evaluate_goal(
        self,
        target_concept: str,
        facts: Sequence[XbrlFact],
        calculation_arcs: Sequence[CalculationArc],
    ) -> SolvedGoal:
        """Evaluate a financial concept directly or via multi-hop calculation roll-up."""
        fact_vals: dict[str, float] = {
            f.concept_qname: float(f.value)
            for f in facts
            if not f.dimensions and isinstance(f.value, (int, float))
        }

        # Direct fact match
        if target_concept in fact_vals:
            return SolvedGoal(
                target_concept=target_concept,
                computed_value=fact_vals[target_concept],
                resolution_tier="DIRECT_ANCHOR",
                is_direct=True,
            )

        # Multi-hop derivation via calculation arcs
        child_arcs = [a for a in calculation_arcs if a.parent_qname == target_concept]
        if child_arcs:
            total = 0.0
            path: list[str] = []
            all_resolved = True
            for arc in child_arcs:
                if arc.child_qname in fact_vals:
                    val = fact_vals[arc.child_qname]
                    total += val * arc.weight
                    path.append(f"{arc.child_qname} * {arc.weight}")
                else:
                    all_resolved = False
                    break
            if all_resolved and path:
                return SolvedGoal(
                    target_concept=target_concept,
                    computed_value=round(total, 4),
                    resolution_tier="DERIVED_MULTI_HOP",
                    derivation_path=tuple(path),
                    is_direct=False,
                )

        return SolvedGoal(
            target_concept=target_concept,
            computed_value=None,
            resolution_tier="UNRESOLVED",
        )
