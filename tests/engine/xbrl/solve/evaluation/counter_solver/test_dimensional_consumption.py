"""Dimensional targets: per-context consumption and slice balancing."""

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.solve.evaluation.counter_solver import CounterSolver
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.solve.core.identities import verified_eps_facts
from edgar_sec.engine.xbrl.solve.core.solver import XbrlConstraintSolver
from tests.engine.xbrl.solve.conftest import (
    load_seed_calculation_arcs,
    load_seed_facts,
)
from tests.engine.xbrl.solve.evaluation.counter_solver.conftest import (
    _ARCS,
    _ASSETS,
    _DIM_A,
    _DIM_B,
    _OBLIGATION,
    _PARENT,
    _NoFallbackSolver,
    _dim_fact,
    _undim_fact,
)


def test_dimensional_target_consumes_only_balanced_contexts() -> None:
    """Verify per-context consumption for a dimensioned-only calc parent."""
    tax = load_domain_taxonomy()
    kb = EvidenceKnowledgeBase(taxonomy=tax)
    counter = CounterSolver(XbrlConstraintSolver(kb))
    acc = AccessionNumber("0000950170-24-087843")
    facts = [
        _dim_fact(acc, _PARENT, 100.0, _DIM_A),
        _dim_fact(acc, _ASSETS, 130.0, _DIM_A),
        _dim_fact(acc, _ASSETS, 130.0, _DIM_A),
        _dim_fact(acc, _OBLIGATION, 30.0, _DIM_A),
        _dim_fact(acc, _PARENT, -20.0, _DIM_B),
        _dim_fact(acc, _ASSETS, 10.0, _DIM_B),
        _dim_fact(acc, _OBLIGATION, 30.0, _DIM_B),
        _dim_fact(acc, _PARENT, 50.0, _DIM_A, instant="2023-12-31"),
        _dim_fact(acc, _ASSETS, 50.0, _DIM_A, instant="2023-12-31"),
        _dim_fact(acc, _PARENT, 999.0, _DIM_A, instant="2022-12-31"),
        _dim_fact(acc, _ASSETS, 10.0, _DIM_A, instant="2022-12-31"),
        _dim_fact(acc, _OBLIGATION, 5.0, _DIM_A, instant="2022-12-31"),
        XbrlFact(
            acc,
            _ASSETS,
            12345.0,
            unit="USD",
            period_type="instant",
            instant_date="2024-12-31",
        ),
    ]
    outcome = counter.audit_filing(
        facts,
        target_goals=[],
        calculation_arcs=_ARCS,
        dimensional_target_goals=[_PARENT],
    )
    total_partition = (
        len(outcome.solved_facts)
        + len(outcome.rejected_facts)
        + len(outcome.quarantined_facts)
    )
    assert total_partition == len(facts)
    assert len(outcome.solved_facts) == 7
    quarantined = {
        (q.fact.concept_qname, q.fact.instant_date) for q in outcome.quarantined_facts
    }
    assert quarantined == {
        (_PARENT, "2023-12-31"),
        (_ASSETS, "2023-12-31"),
        (_PARENT, "2022-12-31"),
        (_ASSETS, "2022-12-31"),
        (_OBLIGATION, "2022-12-31"),
        (_ASSETS, "2024-12-31"),
    }


def test_dimensional_targets_skip_atom_fallback_tiers() -> None:
    """Verify dimensional targets never route through evaluate_goal."""
    counter = CounterSolver(_NoFallbackSolver())  # type: ignore[arg-type]
    acc = AccessionNumber("0000950170-24-087843")
    facts = [
        _dim_fact(acc, _PARENT, 999.0, _DIM_A),
        _dim_fact(acc, _ASSETS, 10.0, _DIM_A),
        _dim_fact(acc, _OBLIGATION, 5.0, _DIM_A),
    ]
    outcome = counter.audit_filing(
        facts,
        target_goals=[],
        calculation_arcs=_ARCS,
        dimensional_target_goals=[_PARENT],
    )
    assert len(outcome.solved_facts) == 0
    assert len(outcome.quarantined_facts) == 3


def test_bac_dimensioned_only_parent_consumed_per_context() -> None:
    """Verify the BAC 2024 specimen balances in all 8 parent contexts."""
    counter = CounterSolver(_NoFallbackSolver())  # type: ignore[arg-type]
    facts = load_seed_facts("bac_2024_10k")
    arcs = load_seed_calculation_arcs("bac_2024_10k")
    outcome = counter.audit_filing(
        facts,
        target_goals=[],
        calculation_arcs=arcs,
        dimensional_target_goals=[_PARENT],
    )
    parent_facts = [f for f in facts if f.concept_qname == _PARENT]
    solved_parent = [f for f in outcome.solved_facts if f.concept_qname == _PARENT]
    assert len(solved_parent) == len(parent_facts) == 8

    def semantic(fact: XbrlFact) -> tuple:
        return (
            fact.concept_qname,
            fact.instant_date,
            tuple(sorted(fact.dimensions.items())),
            float(fact.value),
        )

    # 24 dimensional semantics plus the EPS-identity consumption.
    assert len({semantic(f) for f in outcome.solved_facts}) == 24 + len(
        verified_eps_facts(facts)
    )
    parent_contexts = {
        (f.instant_date, tuple(sorted(f.dimensions.items()))) for f in parent_facts
    }
    assert all(
        (f.instant_date, tuple(sorted(f.dimensions.items()))) in parent_contexts
        for f in solved_parent
    )
    undimensioned_assets = [
        q.fact
        for q in outcome.quarantined_facts
        if q.fact.concept_qname == _ASSETS and not q.fact.dimensions
    ]
    assert len(undimensioned_assets) == 2


def test_anchored_parent_consumes_dimensioned_subtree_per_context() -> None:
    """Verify an anchored parent's balanced context consumes its subtree."""
    counter = CounterSolver(_NoFallbackSolver())  # type: ignore[arg-type]
    acc = AccessionNumber("0000950170-24-087843")
    facts = [
        _undim_fact(acc, _PARENT, 100.0),
        _undim_fact(acc, _ASSETS, 130.0),
        _dim_fact(acc, _PARENT, 70.0, _DIM_A),
        _dim_fact(acc, _ASSETS, 100.0, _DIM_A),
        _dim_fact(acc, _ASSETS, 100.0, _DIM_A),
        _dim_fact(acc, _OBLIGATION, 30.0, _DIM_A),
        _dim_fact(acc, _PARENT, 70.0, _DIM_A, instant="2023-12-31"),
        _dim_fact(acc, _ASSETS, 100.0, _DIM_A, instant="2023-12-31"),
    ]
    outcome = counter.audit_filing(
        facts,
        target_goals=[],
        calculation_arcs=_ARCS,
        anchored_target_goals=[_PARENT, _ASSETS],
    )
    solved_dim = [f for f in outcome.solved_facts if f.dimensions]
    assert len(solved_dim) == 4
    assert all(f.instant_date == "2024-12-31" for f in solved_dim)
    quarantined_dim = [q.fact for q in outcome.quarantined_facts if q.fact.dimensions]
    assert {(f.concept_qname, f.instant_date) for f in quarantined_dim} == {
        (_PARENT, "2023-12-31"),
        (_ASSETS, "2023-12-31"),
    }


def test_slice_group_balancing_reported_total_is_consumed() -> None:
    """Verify slices are consumed only at the anchored (unit, period)."""
    counter = CounterSolver(_NoFallbackSolver())  # type: ignore[arg-type]
    acc = AccessionNumber("0000950170-24-087843")
    geo_a = {"test:GeoAxis": "test:DomesticMember"}
    geo_b = {"test:GeoAxis": "test:ForeignMember"}
    facts = [
        _undim_fact(acc, _ASSETS, 100.0),
        _dim_fact(acc, _ASSETS, 60.0, _DIM_A),
        _dim_fact(acc, _ASSETS, 60.0, _DIM_A),
        _dim_fact(acc, _ASSETS, 40.0, _DIM_B),
        _dim_fact(acc, _ASSETS, 60.0, _DIM_A, instant="2023-12-31"),
        _dim_fact(acc, _ASSETS, 40.0, _DIM_B, instant="2023-12-31"),
        _dim_fact(acc, _ASSETS, 25.0, geo_a),
        _dim_fact(acc, _ASSETS, 25.0, geo_b),
    ]
    outcome = counter.audit_filing(
        facts,
        target_goals=[],
        calculation_arcs=_ARCS,
        anchored_target_goals=[_ASSETS],
    )
    solved_dim = [f for f in outcome.solved_facts if f.dimensions]
    assert len(solved_dim) == 3
    assert all(f.instant_date == "2024-12-31" for f in solved_dim)
    assert all(
        set(f.dimensions) == {"us-gaap:RetirementPlanTypeAxis"} for f in solved_dim
    )
    quarantined_dim = [q.fact for q in outcome.quarantined_facts if q.fact.dimensions]
    assert len(quarantined_dim) == 4


def _dim_fact_decimals(
    acc: AccessionNumber,
    qname: str,
    value: float,
    dimensions: dict[str, str],
    decimals: int | None,
) -> XbrlFact:
    return XbrlFact(
        acc,
        qname,
        value,
        unit="USD",
        period_type="instant",
        instant_date="2024-12-31",
        dimensions=dimensions,
        decimals=decimals,
    )


def test_dimensional_context_balancing_within_filed_precision_is_consumed() -> None:
    """Verify a sum off by one rounding unit of the filed precision balances."""
    counter = CounterSolver(_NoFallbackSolver())  # type: ignore[arg-type]
    acc = AccessionNumber("0000950170-24-087843")
    facts = [
        _dim_fact_decimals(acc, _PARENT, 19_000_000.0, _DIM_A, -6),
        _dim_fact_decimals(acc, _ASSETS, 21_000_000.0, _DIM_A, -6),
        _dim_fact_decimals(acc, _OBLIGATION, 1_000_000.0, _DIM_A, -6),
        _dim_fact_decimals(acc, _PARENT, 19_000_000.0, _DIM_B, -6),
        _dim_fact_decimals(acc, _ASSETS, 25_000_000.0, _DIM_B, -6),
        _dim_fact_decimals(acc, _OBLIGATION, 1_000_000.0, _DIM_B, -6),
    ]
    outcome = counter.audit_filing(
        facts,
        target_goals=[],
        calculation_arcs=_ARCS,
        dimensional_target_goals=[_PARENT],
    )
    solved = {
        (f.concept_qname, tuple(sorted(f.dimensions.items())))
        for f in outcome.solved_facts
    }
    assert len(outcome.solved_facts) == 3
    assert all(dims == tuple(sorted(_DIM_A.items())) for _q, dims in solved)
    assert len(outcome.quarantined_facts) == 3


def test_slice_anchor_fact_is_consumed_when_group_balances() -> None:
    """Verify the verifying undimensioned total is consumed with its slices."""
    counter = CounterSolver(_NoFallbackSolver())  # type: ignore[arg-type]
    acc = AccessionNumber("0000950170-24-087843")
    facts = [
        _undim_fact(acc, _ASSETS, 100.0),
        _dim_fact(acc, _ASSETS, 60.0, _DIM_A),
        _dim_fact(acc, _ASSETS, 40.0, _DIM_B),
    ]
    outcome = counter.audit_filing(
        facts,
        target_goals=[],
        calculation_arcs=_ARCS,
        anchored_target_goals=[_ASSETS],
    )
    assert len(outcome.solved_facts) == 3
    assert not outcome.quarantined_facts


def test_slice_group_balancing_within_filed_precision_is_consumed() -> None:
    """Verify a slice sum within the filed precision of its anchor balances."""
    counter = CounterSolver(_NoFallbackSolver())  # type: ignore[arg-type]
    acc = AccessionNumber("0000950170-24-087843")
    anchor = XbrlFact(
        acc,
        _ASSETS,
        19_000_000.0,
        unit="USD",
        period_type="instant",
        instant_date="2024-12-31",
        decimals=-6,
    )
    facts = [
        anchor,
        _dim_fact_decimals(acc, _ASSETS, 12_000_000.0, _DIM_A, -6),
        _dim_fact_decimals(acc, _ASSETS, 8_000_000.0, _DIM_B, -6),
    ]
    outcome = counter.audit_filing(
        facts,
        target_goals=[],
        calculation_arcs=_ARCS,
        anchored_target_goals=[_ASSETS],
    )
    assert len(outcome.solved_facts) == 3
    assert not outcome.quarantined_facts


_FINE_A = {**_DIM_A, "test:GeoAxis": "test:DomesticMember"}
_FINE_B = {**_DIM_A, "test:GeoAxis": "test:ForeignMember"}


def test_child_filed_only_at_finer_contexts_is_consumed() -> None:
    """Verify finer-context child facts aggregating to the parent balance it."""
    counter = CounterSolver(_NoFallbackSolver())  # type: ignore[arg-type]
    acc = AccessionNumber("0000950170-24-087843")
    facts = [
        _dim_fact(acc, _PARENT, 30.0, _DIM_A),
        _dim_fact(acc, _ASSETS, 30.0, _FINE_A),
        _dim_fact(acc, _ASSETS, 20.0, _FINE_B),
        _dim_fact(acc, _OBLIGATION, 20.0, _DIM_A),
    ]
    outcome = counter.audit_filing(
        facts,
        target_goals=[],
        calculation_arcs=_ARCS,
        dimensional_target_goals=[_PARENT],
    )
    assert len(outcome.solved_facts) == 4
    assert not outcome.quarantined_facts


def test_finer_contexts_not_summing_to_parent_stay_quarantined() -> None:
    """Verify a finer breakdown that misses the parent total consumes nothing."""
    counter = CounterSolver(_NoFallbackSolver())  # type: ignore[arg-type]
    acc = AccessionNumber("0000950170-24-087843")
    facts = [
        _dim_fact(acc, _PARENT, 30.0, _DIM_A),
        _dim_fact(acc, _ASSETS, 30.0, _FINE_A),
        _dim_fact(acc, _ASSETS, 25.0, _FINE_B),
        _dim_fact(acc, _OBLIGATION, 20.0, _DIM_A),
    ]
    outcome = counter.audit_filing(
        facts,
        target_goals=[],
        calculation_arcs=_ARCS,
        dimensional_target_goals=[_PARENT],
    )
    assert len(outcome.solved_facts) == 0
    assert len(outcome.quarantined_facts) == 4


def test_disagreeing_finer_breakdowns_stay_quarantined() -> None:
    """Verify competing finer breakdowns must agree before either is spent."""
    counter = CounterSolver(_NoFallbackSolver())  # type: ignore[arg-type]
    acc = AccessionNumber("0000950170-24-087843")
    sponsor = {**_DIM_A, "test:SponsorAxis": "test:SponsorMember"}
    facts = [
        _dim_fact(acc, _PARENT, 30.0, _DIM_A),
        _dim_fact(acc, _ASSETS, 30.0, _FINE_A),
        _dim_fact(acc, _ASSETS, 20.0, _FINE_B),
        _dim_fact(acc, _ASSETS, 48.0, sponsor),
        _dim_fact(acc, _OBLIGATION, 20.0, _DIM_A),
    ]
    outcome = counter.audit_filing(
        facts,
        target_goals=[],
        calculation_arcs=_ARCS,
        dimensional_target_goals=[_PARENT],
    )
    assert len(outcome.solved_facts) == 0
    assert len(outcome.quarantined_facts) == 5


def test_ambiguous_finer_value_stays_quarantined() -> None:
    """Verify a finer context with two filed values invalidates its group."""
    counter = CounterSolver(_NoFallbackSolver())  # type: ignore[arg-type]
    acc = AccessionNumber("0000950170-24-087843")
    facts = [
        _dim_fact(acc, _PARENT, 30.0, _DIM_A),
        _dim_fact(acc, _ASSETS, 30.0, _FINE_A),
        _dim_fact(acc, _ASSETS, 31.0, _FINE_A),
        _dim_fact(acc, _ASSETS, 20.0, _FINE_B),
        _dim_fact(acc, _OBLIGATION, 20.0, _DIM_A),
    ]
    outcome = counter.audit_filing(
        facts,
        target_goals=[],
        calculation_arcs=_ARCS,
        dimensional_target_goals=[_PARENT],
    )
    assert len(outcome.solved_facts) == 0
    assert len(outcome.quarantined_facts) == 5


def test_unanchored_dimensioned_only_concept_stays_quarantined() -> None:
    """Verify self-summing slices without an anchor or calc role stay out."""
    counter = CounterSolver(_NoFallbackSolver())  # type: ignore[arg-type]
    acc = AccessionNumber("0000950170-24-087843")
    concept = "custom:NoteStatedRateDetail"
    facts = [
        _dim_fact(acc, concept, 100.0, {"custom:InstrumentAxis": "custom:AllMember"}),
        _dim_fact(acc, concept, 60.0, {"custom:InstrumentAxis": "custom:TermLoan"}),
        _dim_fact(acc, concept, 40.0, {"custom:InstrumentAxis": "custom:Revolver"}),
    ]
    outcome = counter.audit_filing(
        facts,
        target_goals=[],
        calculation_arcs=_ARCS,
        anchored_target_goals=[concept],
    )
    assert len(outcome.solved_facts) == 0
    assert len(outcome.quarantined_facts) == 3
