"""Quarantine reason vocabulary: the pinned K1-K4 reason per specimen."""

from dataclasses import fields

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.solve.evaluation.counter_solver import (
    QUARANTINE_REASONS,
    CounterSolver,
    QuarantinedFact,
)
from edgar_sec.engine.xbrl.schema.models import CalculationArc
from tests.engine.xbrl.solve.evaluation.counter_solver.conftest import (
    _ARCS,
    _ASSETS,
    _DIM_A,
    _DIM_B,
    _OBLIGATION,
    _PARENT,
    _NoFallbackSolver,
    _dim_fact,
    _reason_by_concept,
    _undim_fact,
)


def test_quarantine_reason_vocabulary_is_pinned() -> None:
    """Verify the pair-level reason vocabulary and the slim record shape."""
    assert QUARANTINE_REASONS == (
        "DIMENSIONED_ONLY_NO_CALC_ROLE",
        "DIMENSIONED_ONLY_IN_CALC_ARCS",
        "DIMENSIONED_ONLY_IN_CALC_ARCS_PARTIALLY_CONSUMED",
        "UNDIMENSIONED_NO_CALC_ROLE",
        "UNDIMENSIONED_CALC_ISOLATED",
        "UNDIMENSIONED_IN_CALC_ARCS_NOT_CONSUMED",
        "UNDIMENSIONED_IN_CALC_ARCS_PARENT_NOT_AUDITED",
    )
    assert {field.name for field in fields(QuarantinedFact)} == {"fact", "reason"}


def test_quarantine_reason_dimensioned_only_no_calc_role() -> None:
    """Verify dimensioned-only facts without a calc role are K1."""
    counter = CounterSolver(_NoFallbackSolver())  # type: ignore[arg-type]
    acc = AccessionNumber("0000950170-24-087843")
    concept = "custom:NoteStatedRateDetail"
    facts = [
        _dim_fact(acc, concept, 10.0, _DIM_A),
        _dim_fact(acc, concept, 20.0, _DIM_B),
    ]
    outcome = counter.audit_filing(facts, target_goals=[], calculation_arcs=[])
    assert len(outcome.quarantined_facts) == 2
    assert {q.reason for q in outcome.quarantined_facts} == {
        "DIMENSIONED_ONLY_NO_CALC_ROLE"
    }


def test_quarantine_reason_dimensioned_only_in_calc_arcs() -> None:
    """Verify dimensioned-only calc members never audited are K2."""
    counter = CounterSolver(_NoFallbackSolver())  # type: ignore[arg-type]
    acc = AccessionNumber("0000950170-24-087843")
    facts = [
        _dim_fact(acc, _PARENT, 100.0, _DIM_A),
        _dim_fact(acc, _ASSETS, 130.0, _DIM_A),
        _dim_fact(acc, _OBLIGATION, 30.0, _DIM_A),
    ]
    outcome = counter.audit_filing(facts, target_goals=[], calculation_arcs=_ARCS)
    assert _reason_by_concept(outcome) == {
        _PARENT: "DIMENSIONED_ONLY_IN_CALC_ARCS",
        _ASSETS: "DIMENSIONED_ONLY_IN_CALC_ARCS",
        _OBLIGATION: "DIMENSIONED_ONLY_IN_CALC_ARCS",
    }


def test_quarantine_reason_dimensioned_only_partially_consumed() -> None:
    """Verify a pair with one balanced context consumed is the extension."""
    counter = CounterSolver(_NoFallbackSolver())  # type: ignore[arg-type]
    acc = AccessionNumber("0000950170-24-087843")
    facts = [
        _dim_fact(acc, _PARENT, 100.0, _DIM_A),
        _dim_fact(acc, _ASSETS, 130.0, _DIM_A),
        _dim_fact(acc, _OBLIGATION, 30.0, _DIM_A),
        _dim_fact(acc, _ASSETS, 10.0, _DIM_B, instant="2023-12-31"),
    ]
    outcome = counter.audit_filing(
        facts,
        target_goals=[],
        calculation_arcs=_ARCS,
        dimensional_target_goals=[_PARENT],
    )
    assert len(outcome.quarantined_facts) == 1
    assert outcome.quarantined_facts[0].fact.concept_qname == _ASSETS
    assert (
        outcome.quarantined_facts[0].reason
        == "DIMENSIONED_ONLY_IN_CALC_ARCS_PARTIALLY_CONSUMED"
    )


def test_quarantine_reason_undimensioned_no_calc_role() -> None:
    """Verify undimensioned facts without a calc role are K3."""
    counter = CounterSolver(_NoFallbackSolver())  # type: ignore[arg-type]
    acc = AccessionNumber("0000950170-24-087843")
    facts = [_undim_fact(acc, "custom:PerShareMetric", 5.0)]
    outcome = counter.audit_filing(facts, target_goals=[], calculation_arcs=[])
    assert _reason_by_concept(outcome) == {
        "custom:PerShareMetric": "UNDIMENSIONED_NO_CALC_ROLE"
    }


def test_quarantine_reason_parent_not_audited() -> None:
    """Verify a calc child whose parent was never audited is K4b."""
    counter = CounterSolver(_NoFallbackSolver())  # type: ignore[arg-type]
    acc = AccessionNumber("0000950170-24-087843")
    facts = [
        _dim_fact(acc, _PARENT, 100.0, _DIM_A),
        _undim_fact(acc, _ASSETS, 10.0),
    ]
    arcs = [CalculationArc(_PARENT, _ASSETS, weight=1.0)]
    outcome = counter.audit_filing(facts, target_goals=[], calculation_arcs=arcs)
    assert _reason_by_concept(outcome) == {
        _PARENT: "DIMENSIONED_ONLY_IN_CALC_ARCS",
        _ASSETS: "UNDIMENSIONED_IN_CALC_ARCS_PARENT_NOT_AUDITED",
    }


def test_quarantine_reason_in_calc_arcs_not_consumed() -> None:
    """Verify a calc child of an audited parent left over is K4a."""
    counter = CounterSolver(_NoFallbackSolver())  # type: ignore[arg-type]
    acc = AccessionNumber("0000950170-24-087843")
    facts = [
        _dim_fact(acc, _PARENT, 100.0, _DIM_A),
        _undim_fact(acc, _ASSETS, 10.0),
    ]
    arcs = [CalculationArc(_PARENT, _ASSETS, weight=1.0)]
    outcome = counter.audit_filing(
        facts,
        target_goals=[],
        calculation_arcs=arcs,
        dimensional_target_goals=[_PARENT],
    )
    assert _reason_by_concept(outcome)[_ASSETS] == (
        "UNDIMENSIONED_IN_CALC_ARCS_NOT_CONSUMED"
    )


def test_quarantine_reason_audited_root_not_consumed() -> None:
    """Verify an audited parent-only concept left over is also K4a."""
    counter = CounterSolver(_NoFallbackSolver())  # type: ignore[arg-type]
    acc = AccessionNumber("0000950170-24-087843")
    facts = [
        _undim_fact(acc, _PARENT, 100.0),
        _undim_fact(acc, _ASSETS, 10.0),
    ]
    arcs = [CalculationArc(_PARENT, _ASSETS, weight=1.0)]
    outcome = counter.audit_filing(
        facts,
        target_goals=[],
        calculation_arcs=arcs,
        dimensional_target_goals=[_PARENT],
    )
    assert _reason_by_concept(outcome) == {
        _PARENT: "UNDIMENSIONED_IN_CALC_ARCS_NOT_CONSUMED",
        _ASSETS: "UNDIMENSIONED_IN_CALC_ARCS_NOT_CONSUMED",
    }
