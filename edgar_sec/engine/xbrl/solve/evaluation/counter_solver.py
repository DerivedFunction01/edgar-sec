"""Counter-solver implementing Epistemic Quarantine and Conservation of Facts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from edgar_sec.engine.xbrl.evidence.evidence import UnificationRule
from edgar_sec.engine.xbrl.schema.models import (
    AggregateFact,
    CalculationArc,
    ConceptDeclaration,
    XbrlFact,
    qname_local,
)
from edgar_sec.engine.xbrl.solve.core.identities import verified_eps_facts
from edgar_sec.engine.xbrl.solve.core.solver import XbrlConstraintSolver
from edgar_sec.engine.xbrl.solve.evaluation.counter_consumption import ConsumptionMixin
from edgar_sec.engine.xbrl.solve.evaluation.counter_hypotheses import (
    AuditHypothesis,
    TypedHypothesesMixin,
)
from edgar_sec.engine.xbrl.solve.evaluation.counter_keys import _semantic_key
from edgar_sec.engine.xbrl.solve.evaluation.counter_quarantine import (
    PairReasonsMixin,
    QuarantinedFact,
)


@dataclass(frozen=True, slots=True)
class CounterSolverOutcome:
    """Complete accounting partition of filing facts and induced hypotheses."""

    solved_facts: tuple[XbrlFact, ...]
    rejected_facts: tuple[XbrlFact, ...]
    quarantined_facts: tuple[QuarantinedFact, ...]
    hypotheses: tuple[AuditHypothesis, ...]


class CounterSolver(ConsumptionMixin, PairReasonsMixin, TypedHypothesesMixin):
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
        identity_consumed = {_semantic_key(fact) for fact in verified_eps_facts(facts)}
        consumed_keys = dimensional_consumed | identity_consumed

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
            if isinstance(f.value, (int, float)) and _semantic_key(f) in consumed_keys:
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
        reasons = self._pair_reasons(
            solved, unconsumed, calculation_arcs, audited, declarations
        )
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
