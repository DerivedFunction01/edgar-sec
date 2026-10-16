"""Public coordinator for XBRL placement and aggregate solving."""

from __future__ import annotations

from collections.abc import Sequence

from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.schema.models import (
    AggregateFact,
    CalculationArc,
    ConceptBreakdown,
    Verdict,
    XbrlFact,
)
from edgar_sec.engine.xbrl.solve.antichain import (
    AntiChainOutcome,
    AntiChainValidator,
    CandidateFrontier,
)
from edgar_sec.engine.xbrl.solve.breakdown import breakdown_concept
from edgar_sec.engine.xbrl.solve.candidates import classify_candidate_facts
from edgar_sec.engine.xbrl.solve.evaluation import AggregateEvaluator
from edgar_sec.engine.xbrl.solve.frontier import (
    resolve_query_frontier,
    verify_non_double_counting,
)
from edgar_sec.engine.xbrl.solve.gold import PlacementPrediction
from edgar_sec.engine.xbrl.solve.placement import solve_placements


SOLVER_FINGERPRINT = "xbrl-solver-v1"


class XbrlConstraintSolver:
    """Coordinate XBRL evidence, placement rules, and aggregate evaluation."""

    def __init__(
        self,
        kb: EvidenceKnowledgeBase,
        *,
        enable_head_induction: bool = True,
    ) -> None:
        self.kb = kb
        self.enable_head_induction = enable_head_induction
        self.antichain_validator = AntiChainValidator()
        self._evaluator = AggregateEvaluator(kb, self.antichain_validator)

    def _verify_non_double_counting(
        self,
        selected_concepts: Sequence[str],
        calculation_arcs: Sequence[CalculationArc],
    ) -> AntiChainOutcome:
        return verify_non_double_counting(
            self.antichain_validator,
            self.kb.taxonomy,
            selected_concepts,
            calculation_arcs,
        )

    def resolve_query_frontier(
        self,
        query_concept: str,
        facts: Sequence[XbrlFact],
        calculation_arcs: Sequence[CalculationArc] = (),
    ) -> CandidateFrontier:
        return resolve_query_frontier(
            self.antichain_validator,
            self.kb.taxonomy,
            query_concept,
            facts,
            calculation_arcs,
        )

    def solve_placements(
        self,
        facts: Sequence[XbrlFact],
        calculation_arcs: Sequence[CalculationArc] = (),
        *,
        firm: str = "",
        sector: str = "",
        year: int | str = "",
    ) -> tuple[PlacementPrediction, ...]:
        return solve_placements(
            self.kb,
            facts,
            calculation_arcs,
            firm=firm,
            sector=sector,
            year=year,
            enable_head_induction=self.enable_head_induction,
        )

    def breakdown_concept(
        self,
        target_concept: str,
        facts: Sequence[XbrlFact],
        calculation_arcs: Sequence[CalculationArc] = (),
        *,
        axis: str | None = None,
    ) -> ConceptBreakdown:
        return breakdown_concept(
            self.kb, target_concept, facts, calculation_arcs, axis=axis
        )

    def classify_candidate_facts(
        self,
        target_concept: str,
        facts: Sequence[XbrlFact],
        calculation_arcs: Sequence[CalculationArc] = (),
    ) -> tuple[Verdict, ...]:
        return classify_candidate_facts(target_concept, facts, calculation_arcs)

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
        return self._evaluator.evaluate_goal(
            target_concept,
            facts,
            calculation_arcs,
            axis_filter=axis_filter,
            entity=entity,
            period=period,
            unit=unit,
            _visited=_visited,
        )
