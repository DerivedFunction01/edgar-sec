"""Declarative GoalSpec, GoalFixture, and GoalPack contracts for frozen query verification."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from edgar_sec.engine.xbrl.schema.models import AggregateFact, CalculationArc, XbrlFact
from edgar_sec.engine.xbrl.normalize.normalization import normalize_fact
from edgar_sec.engine.xbrl.solve.solver import XbrlConstraintSolver


@dataclass(frozen=True, slots=True)
class GoalSpec:
    """Declarative specification of a target financial aggregate and tolerance constraints."""

    goal_id: str
    target_measure: str
    time_class: str = "ANNUAL"
    unit_class: str = "USD"
    slice_dimension: str | None = None
    decomposition_scheme: str | None = None
    identity_formulas: tuple[str, ...] = ()
    tolerance_rel: float = 0.01
    tolerance_abs: float = 1000.0


@dataclass(frozen=True, slots=True)
class GoalFixture:
    """Certified reference observation for evaluating GoalPack accuracy."""

    entity: str
    accession: str
    expected_basis: str
    expected_value: float | None = None
    tolerance: float = 1.0
    period: str = ""


@dataclass(frozen=True, slots=True)
class GoalPack:
    """Frozen declarative contract uniting a GoalSpec, test fixtures, and quality gates."""

    spec: GoalSpec
    version: str = "1.0.0"
    fixtures: tuple[GoalFixture, ...] = field(default_factory=tuple)
    min_precision: float = 0.99
    min_coverage: float = 0.80

    def evaluate(
        self,
        solver: XbrlConstraintSolver,
        facts: tuple[XbrlFact, ...] | list[XbrlFact],
        calculation_arcs: tuple[CalculationArc, ...] | list[CalculationArc] = (),
        *,
        entity: str = "",
        period: str = "",
    ) -> AggregateFact:
        """Evaluate the goal against filing facts matching the normalized coordinates."""
        matched_facts = [f for f in facts if self._matches_coordinates(f)]
        return solver.evaluate_goal(
            target_concept=self.spec.target_measure,
            facts=matched_facts or facts,
            calculation_arcs=calculation_arcs,
            axis_filter=self.spec.slice_dimension,
            entity=entity,
            period=period,
            unit=self.spec.unit_class,
        )

    def _matches_coordinates(self, fact: XbrlFact) -> bool:
        norm = normalize_fact(fact)
        if self.spec.unit_class and norm.unit_class != self.spec.unit_class:
            return False
        if self.spec.time_class and norm.time.length_class != self.spec.time_class:
            if not (norm.time.kind == "INSTANT" and self.spec.time_class == "INSTANT"):
                return False
        return True
