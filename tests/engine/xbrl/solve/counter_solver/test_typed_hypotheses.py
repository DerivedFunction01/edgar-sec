"""Typed residual-component hypotheses: emission and eligibility."""

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.solve.counter_solver import CounterSolver
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.schema.models import CalculationArc, XbrlFact
from tests.engine.xbrl.solve.counter_solver.conftest import (
    _StubPrimarySolver,
    _decls,
)


_ACC = AccessionNumber("0000950170-24-087843")
_TARGET = "test:RevenueTotal"
_CHILD = "test:RevenueCore"
_SOURCE = "test:RevenueTotalAdjustment"


def _typed_fact(
    qname: str,
    value: float,
    *,
    unit: str = "USD",
    instant: str = "2024-12-31",
    dimensions: dict[str, str] | None = None,
) -> XbrlFact:
    return XbrlFact(
        _ACC,
        qname,
        value,
        unit=unit,
        period_type="instant",
        instant_date=instant,
        dimensions=dimensions or {},
    )


def _typed_outcome(facts, arcs, goals, declarations):  # noqa: ANN001, ANN202
    """Audit synthetic facts through the stub solver and real taxonomy."""
    kb = EvidenceKnowledgeBase(load_domain_taxonomy())
    counter = CounterSolver(_StubPrimarySolver(kb))  # type: ignore[arg-type]
    return counter.audit_filing(
        facts,
        target_goals=goals,
        calculation_arcs=arcs,
        declarations=declarations,
    )


def _base_case(source_value: float = 10.0, **source_kwargs) -> tuple:  # noqa: ANN003, ANN202
    """One goal with a 10.0 residual and one quarantined source fact."""
    facts = [
        _typed_fact(_TARGET, 100.0),
        _typed_fact(_CHILD, 90.0),
        _typed_fact(_SOURCE, source_value, **source_kwargs),
    ]
    arcs = [CalculationArc(_TARGET, _CHILD, weight=1.0)]
    return facts, arcs, [_TARGET], _decls(_TARGET, _CHILD, _SOURCE)


def test_typed_hypothesis_positive_control() -> None:
    """Verify a genuine typed residual component is emitted typed."""
    facts, arcs, goals, declarations = _base_case()
    outcome = _typed_outcome(facts, arcs, goals, declarations)
    assert len(outcome.hypotheses) == 1
    hypothesis = outcome.hypotheses[0]
    assert hypothesis.concept_qname == _SOURCE
    assert hypothesis.hypothesized_parent == _TARGET
    assert hypothesis.hypothesis_type == "RESIDUAL_COMPONENT"
    assert hypothesis.algebraic_weight == 1.0
    assert hypothesis.residual_delta < 1e-4
    assert hypothesis.period == "2024-12-31"
    assert not hasattr(hypothesis, "confidence")


def test_derived_weight_is_the_closing_sign() -> None:
    """Verify the weight derives from the signed residual, not a constant."""
    facts, arcs, goals, declarations = _base_case(source_value=-10.0)
    outcome = _typed_outcome(facts, arcs, goals, declarations)
    assert len(outcome.hypotheses) == 1
    assert outcome.hypotheses[0].algebraic_weight == -1.0

    facts, arcs, goals, declarations = _base_case(source_value=10.0)
    outcome = _typed_outcome(facts, arcs, goals, declarations)
    assert len(outcome.hypotheses) == 1
    assert outcome.hypotheses[0].algebraic_weight == 1.0


def test_rate_and_per_share_targets_emit_nothing() -> None:
    """Verify non-monetary targets never vacuum up small residuals."""
    for target, item_type, unit in (
        ("test:EffectiveTaxRate", "xbrli:percentItemType", "pure"),
        ("test:EarningsPerShare", "xbrli:perShareItemType", "USD/shares"),
    ):
        child = f"{target}Core"
        facts = [
            _typed_fact(target, 50.0, unit=unit),
            _typed_fact(child, 40.0, unit=unit),
            _typed_fact(_SOURCE, 10.0),
        ]
        arcs = [CalculationArc(target, child, weight=1.0)]
        declarations = _decls(_SOURCE)
        declarations.update(_decls(target, child, item_type=item_type))
        outcome = _typed_outcome(facts, arcs, [target], declarations)
        assert outcome.hypotheses == ()


def test_sub_unit_residual_emits_nothing() -> None:
    """Verify a monetary residual under the 1.0 floor is ineligible."""
    facts = [
        _typed_fact(_TARGET, 100.5),
        _typed_fact(_CHILD, 100.0),
        _typed_fact(_SOURCE, 0.5),
    ]
    arcs = [CalculationArc(_TARGET, _CHILD, weight=1.0)]
    outcome = _typed_outcome(facts, arcs, [_TARGET], _decls(_TARGET, _CHILD, _SOURCE))
    assert outcome.hypotheses == ()


def test_nonunique_reported_value_emits_nothing() -> None:
    """Verify a goal with two reported values in one period is ineligible."""
    facts = [
        _typed_fact(_TARGET, 100.0),
        _typed_fact(_TARGET, 101.0),
        _typed_fact(_CHILD, 90.0),
        _typed_fact(_SOURCE, 10.0),
    ]
    arcs = [CalculationArc(_TARGET, _CHILD, weight=1.0)]
    outcome = _typed_outcome(facts, arcs, [_TARGET], _decls(_TARGET, _CHILD, _SOURCE))
    assert outcome.hypotheses == ()


def test_dimensioned_only_source_emits_nothing() -> None:
    """Verify a dimensioned slice is never a residual component."""
    dims = {"test:SegmentAxis": "test:DomesticMember"}
    facts, arcs, goals, declarations = _base_case(dimensions=dims)
    outcome = _typed_outcome(facts, arcs, goals, declarations)
    assert any(q.fact.concept_qname == _SOURCE for q in outcome.quarantined_facts)
    assert outcome.hypotheses == ()


def test_period_mixed_source_emits_nothing() -> None:
    """Verify a source instance from another period cannot close a residual."""
    facts = [
        _typed_fact(_TARGET, 100.0),
        _typed_fact(_CHILD, 90.0),
        _typed_fact(_SOURCE, 10.0, instant="2023-12-31"),
        _typed_fact(_SOURCE, 77.0),
    ]
    arcs = [CalculationArc(_TARGET, _CHILD, weight=1.0)]
    outcome = _typed_outcome(facts, arcs, [_TARGET], _decls(_TARGET, _CHILD, _SOURCE))
    assert outcome.hypotheses == ()


def test_unit_blind_sources_emit_nothing() -> None:
    """Verify share counts and claimant counts never enter monetary goals."""
    share_source = "test:RevenueShareAdjustment"
    count_source = "test:RevenueClaimantAdjustment"
    facts = [
        _typed_fact(_TARGET, 100.0),
        _typed_fact(_CHILD, 90.0),
        _typed_fact(share_source, 10.0, unit="shares"),
        _typed_fact(count_source, 10.0, unit="pure"),
    ]
    arcs = [CalculationArc(_TARGET, _CHILD, weight=1.0)]
    declarations = _decls(_TARGET, _CHILD)
    declarations.update(_decls(share_source, item_type="xbrli:sharesItemType"))
    declarations.update(_decls(count_source, item_type="xbrli:integerItemType"))
    outcome = _typed_outcome(facts, arcs, [_TARGET], declarations)
    assert outcome.hypotheses == ()


def test_ladder_unrelated_source_emits_nothing() -> None:
    """Verify a ladder-UNRELATED monetary coincidence is excluded."""
    source = "test:DebtObligationTotal"
    facts = [
        _typed_fact(_TARGET, 100.0),
        _typed_fact(_CHILD, 90.0),
        _typed_fact(source, 10.0),
    ]
    arcs = [CalculationArc(_TARGET, _CHILD, weight=1.0)]
    outcome = _typed_outcome(facts, arcs, [_TARGET], _decls(_TARGET, _CHILD, source))
    assert outcome.hypotheses == ()


def test_declared_subtree_sources_emit_nothing() -> None:
    """Verify calc-graph relations in both directions are excluded."""
    grandchild = "test:RevenueCoreDetail"
    facts = [
        _typed_fact(_TARGET, 100.0),
        _typed_fact(_CHILD, 90.0),
        _typed_fact(grandchild, 10.0),
    ]
    arcs = [
        CalculationArc(_TARGET, _CHILD, weight=1.0),
        CalculationArc(_CHILD, grandchild, weight=1.0),
    ]
    outcome = _typed_outcome(
        facts, arcs, [_TARGET], _decls(_TARGET, _CHILD, grandchild)
    )
    assert outcome.hypotheses == ()

    parent = "test:RevenueTotal"
    subtotal = "test:RevenueSubtotal"
    sub_child = "test:RevenueSubtotalCore"
    facts = [
        _typed_fact(subtotal, 100.0),
        _typed_fact(sub_child, 90.0),
        _typed_fact(parent, 10.0),
    ]
    arcs = [
        CalculationArc(subtotal, sub_child, weight=1.0),
        CalculationArc(parent, subtotal, weight=1.0),
    ]
    outcome = _typed_outcome(
        facts, arcs, [subtotal], _decls(parent, subtotal, sub_child)
    )
    assert outcome.hypotheses == ()


def test_netting_shape_emits_nothing() -> None:
    """Verify a de-Net substring group sum produces no hypothesis at all."""
    target = "test:IntangibleAssetsNet"
    core = "test:IntangibleAssetsCore"
    amounts = (166.0, 96.0, 33.0, 26.0, 23.0, 55.0)
    sources = [f"test:IntangibleAssetsAmortizationExpense{i}" for i in range(6)]
    facts = [_typed_fact(target, 399.0), _typed_fact(core, 399.0)]
    facts += [
        _typed_fact(source, amount)
        for source, amount in zip(sources, amounts, strict=True)
    ]
    arcs = [CalculationArc(target, core, weight=1.0)]
    outcome = _typed_outcome(facts, arcs, [target], _decls(target, core, *sources))
    assert outcome.hypotheses == ()


def test_two_sources_closing_one_residual_emit_nothing() -> None:
    """Verify ambiguity: two closers for one (goal, period) suppress both."""
    other = "test:RevenueAdjustmentBeta"
    facts, arcs, goals, declarations = _base_case()
    facts.append(_typed_fact(other, 10.0))
    declarations.update(_decls(other))
    outcome = _typed_outcome(facts, arcs, goals, declarations)
    assert outcome.hypotheses == ()


def test_one_source_closing_two_goals_emits_nothing() -> None:
    """Verify ambiguity: one source closing two goals is suppressed."""
    other_target = "test:RevenueNetTotal"
    other_child = "test:RevenueNetCore"
    facts = [
        _typed_fact(_TARGET, 100.0),
        _typed_fact(_CHILD, 90.0),
        _typed_fact(other_target, 200.0),
        _typed_fact(other_child, 190.0),
        _typed_fact(_SOURCE, 10.0),
    ]
    arcs = [
        CalculationArc(_TARGET, _CHILD, weight=1.0),
        CalculationArc(other_target, other_child, weight=1.0),
    ]
    declarations = _decls(_TARGET, _CHILD, other_target, other_child, _SOURCE)
    outcome = _typed_outcome(facts, arcs, [_TARGET, other_target], declarations)
    assert outcome.hypotheses == ()
