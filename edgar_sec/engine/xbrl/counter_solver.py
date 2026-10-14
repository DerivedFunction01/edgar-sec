"""Counter-solver implementing Epistemic Quarantine and Conservation of Facts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from edgar_sec.engine.xbrl.evidence import UnificationRule
from edgar_sec.engine.xbrl.models import CalculationArc, XbrlFact
from edgar_sec.engine.xbrl.solver import AggregateFact, XbrlConstraintSolver


@dataclass(frozen=True, slots=True)
class QuarantinedFact:
    """An unconsumed filing fact captured in Epistemic Quarantine."""

    fact: XbrlFact
    reason: str
    observed_residual: float | None = None
    candidate_parent: str | None = None
    audit_status: str = "UNAUDITED"


@dataclass(frozen=True, slots=True)
class AuditHypothesis:
    """An empirical hypothesis induced from quarantined residual correlations."""

    concept_qname: str
    hypothesized_parent: str
    algebraic_weight: float
    hypothesis_type: str
    confidence: float
    residual_delta: float


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

    def audit_filing(
        self,
        facts: Sequence[XbrlFact],
        target_goals: Sequence[str],
        calculation_arcs: Sequence[CalculationArc] = (),
    ) -> CounterSolverOutcome:
        """Audit filing facts against goals enforcing Conservation of Facts."""
        solved_qnames: set[str] = set()
        goal_residuals: dict[str, float] = {}

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
                    if agg.breakdown.discrepancy > 0.0:
                        goal_residuals[goal] = agg.breakdown.discrepancy
                if agg.components:
                    for comp in agg.components:
                        solved_qnames.add(comp.identifier)

        # 2. Partition facts into solved, rejected, and quarantined via solver placements
        predictions = {
            p.concept_qname: p
            for p in self.primary_solver.solve_placements(facts, calculation_arcs)
        }
        solved: list[XbrlFact] = []
        rejected: list[XbrlFact] = []
        quarantined: list[QuarantinedFact] = []

        for f in facts:
            q_loc = (
                f.concept_qname.split(":")[-1]
                if ":" in f.concept_qname
                else f.concept_qname
            )
            if (
                f.concept_qname in solved_qnames
                or q_loc in solved_qnames
                or any(q_loc in s for s in solved_qnames)
            ):
                solved.append(f)
            elif f.value is None or not isinstance(f.value, (int, float)):
                rejected.append(f)
            else:
                quarantined.append(
                    QuarantinedFact(
                        fact=f,
                        reason="UNMATCHED_IN_PRIMARY_SOLVER",
                    )
                )

        # 3. Zero-Residual Subtotal Audit on Quarantined Facts
        hypotheses: list[AuditHypothesis] = []
        for goal, discrepancy in goal_residuals.items():
            for qf in quarantined:
                if isinstance(qf.fact.value, (int, float)):
                    f_val = abs(float(qf.fact.value))
                    delta = abs(f_val - discrepancy)
                    if delta < 1.0:
                        hypotheses.append(
                            AuditHypothesis(
                                concept_qname=qf.fact.concept_qname,
                                hypothesized_parent=goal,
                                algebraic_weight=-1.0,
                                hypothesis_type="SHADOW_LEAF",
                                confidence=0.85,
                                residual_delta=delta,
                            )
                        )

        # 4. Gross-vs-Net Redundancy Check
        net_facts = [
            f
            for f in solved
            if "Net" in f.concept_qname and isinstance(f.value, (int, float))
        ]
        for nf in net_facts:
            q_candidates = [
                q
                for q in quarantined
                if isinstance(q.fact.value, (int, float))
                and nf.concept_qname.replace("Net", "") in q.fact.concept_qname
            ]
            if q_candidates:
                comp_sum = sum(float(q.fact.value) for q in q_candidates)
                if abs(comp_sum - float(nf.value)) < 1.0:
                    for q in q_candidates:
                        hypotheses.append(
                            AuditHypothesis(
                                concept_qname=q.fact.concept_qname,
                                hypothesized_parent=nf.concept_qname,
                                algebraic_weight=1.0,
                                hypothesis_type="NETTING_REDUNDANCY",
                                confidence=0.95,
                                residual_delta=abs(comp_sum - float(nf.value)),
                            )
                        )

        return CounterSolverOutcome(
            solved_facts=tuple(solved),
            rejected_facts=tuple(rejected),
            quarantined_facts=tuple(quarantined),
            hypotheses=tuple(hypotheses),
        )
