"""Unit tests for CounterSolver and Epistemic Quarantine."""

from dataclasses import fields

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.solve.counter_solver import (
    QUARANTINE_REASONS,
    CounterSolver,
    QuarantinedFact,
)
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.engine.xbrl.evidence.evidence import (
    EvidenceKnowledgeBase,
    UnificationRule,
)
from edgar_sec.engine.xbrl.schema.models import (
    AggregateFact,
    CalculationArc,
    ConceptBreakdown,
    ConceptDeclaration,
    GranularComponent,
    XbrlFact,
)
from edgar_sec.engine.xbrl.solve.solver import XbrlConstraintSolver
from tests.engine.xbrl.solve.conftest import (
    load_seed_calculation_arcs,
    load_seed_facts,
)
from tests.support import bundle_dir

_PARENT = "us-gaap:DefinedBenefitPlanAmountsRecognizedInBalanceSheet"
_ASSETS = "us-gaap:DefinedBenefitPlanFairValueOfPlanAssets"
_OBLIGATION = "us-gaap:DefinedBenefitPlanBenefitObligation"
_DIM_A = {"us-gaap:RetirementPlanTypeAxis": "us-gaap:PensionPlansDefinedBenefitMember"}
_DIM_B = {
    "us-gaap:RetirementPlanTypeAxis": "us-gaap:OtherPensionPlansDefinedBenefitMember"
}
_ARCS = [
    CalculationArc(_PARENT, _ASSETS, weight=1.0),
    CalculationArc(_PARENT, _OBLIGATION, weight=-1.0),
]


def _dim_fact(
    acc: AccessionNumber,
    qname: str,
    value: float,
    dimensions: dict[str, str],
    instant: str = "2024-12-31",
) -> XbrlFact:
    return XbrlFact(
        acc,
        qname,
        value,
        unit="USD",
        period_type="instant",
        instant_date=instant,
        dimensions=dimensions,
    )


class _NoFallbackSolver:
    """Primary-solver stub: any evaluate_goal call is an atom-tier leak."""

    def evaluate_goal(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("evaluate_goal must not run for dimensional targets")

    def solve_placements(self, *args: object, **kwargs: object) -> tuple:
        return ()


def test_conservation_of_facts_quarantine() -> None:
    """Verify that unconsumed facts are strictly partitioned into quarantine."""
    tax = load_domain_taxonomy()
    kb = EvidenceKnowledgeBase(taxonomy=tax)
    primary = XbrlConstraintSolver(kb)
    counter = CounterSolver(primary)
    acc = AccessionNumber("0000950170-24-087843")

    facts = [
        XbrlFact(acc, "us-gaap:Revenues", 100.0),
        XbrlFact(acc, "us-gaap:CostOfGoodsAndServicesSold", 40.0),
        XbrlFact(acc, "msft:CloudInfrastructureRestructuringCharge", 25.0),
        XbrlFact(acc, "custom:NonMonetaryNotice", None),
    ]

    outcome = counter.audit_filing(facts, target_goals=["GrossProfit"])
    # Conservation of Facts Law
    total_partition = (
        len(outcome.solved_facts)
        + len(outcome.rejected_facts)
        + len(outcome.quarantined_facts)
    )
    assert total_partition == len(facts)
    assert len(outcome.quarantined_facts) == 1
    assert (
        outcome.quarantined_facts[0].fact.concept_qname
        == "msft:CloudInfrastructureRestructuringCharge"
    )
    assert len(outcome.rejected_facts) == 1


class _StubPrimarySolver:
    """Primary stub: arc-child goals with a deliberately wrong discrepancy.

    The wrong 999.0 discrepancy proves hypotheses use recomputed residuals.
    """

    def __init__(self, kb: EvidenceKnowledgeBase) -> None:
        self.kb = kb

    def evaluate_goal(self, goal, facts, calculation_arcs):  # noqa: ANN001, ANN202
        """Return the goal with its direct arc children as components."""
        comps = tuple(
            GranularComponent(arc.child_qname, 0.0, arc.weight)
            for arc in calculation_arcs
            if arc.parent_qname == goal
        )
        return AggregateFact(
            goal,
            "entity",
            "",
            "USD",
            1.0,
            "REPORTED",
            components=comps,
            breakdown=ConceptBreakdown(goal, 1.0, comps, False, 999.0),
        )

    def solve_placements(self, facts, calculation_arcs):  # noqa: ANN001, ANN202
        """Place nothing; the partition follows evaluate_goal components."""
        return ()


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


def _decls(*qnames: str, item_type: str = "xbrli:monetaryItemType") -> dict:
    return {
        qname: ConceptDeclaration(qname, qname.split(":")[-1], item_type=item_type)
        for qname in qnames
    }


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


def _seed_declarations(folder: str) -> dict[str, ConceptDeclaration]:
    import pyarrow.parquet as pq

    rows = pq.read_table(bundle_dir(folder) / "declarations.parquet").to_pylist()
    return {
        row["concept_qname"]: ConceptDeclaration(
            concept_qname=row["concept_qname"],
            name=row["name"],
            period_type=row["period_type"],
            balance=row["balance"],
            substitution_group=row["substitution_group"],
            item_type=row["item_type"],
        )
        for row in rows
    }


def _bundle_outcome(folder: str):  # noqa: ANN202
    """Audit one seed bundle through the stub solver and real taxonomy."""
    facts = load_seed_facts(folder)
    arcs = load_seed_calculation_arcs(folder)
    reported = {
        fact.concept_qname
        for fact in facts
        if not fact.dimensions and isinstance(fact.value, (int, float))
    }
    goals = sorted({arc.parent_qname for arc in arcs if arc.parent_qname in reported})
    kb = EvidenceKnowledgeBase(load_domain_taxonomy())
    counter = CounterSolver(_StubPrimarySolver(kb))  # type: ignore[arg-type]
    return counter.audit_filing(
        facts,
        target_goals=goals,
        calculation_arcs=arcs,
        declarations=_seed_declarations(folder),
    )


def test_apd_bundle_eps_and_tax_rate_magnets_emit_nothing() -> None:
    """Verify the APD bundle's rate/EPS magnets produce no hypotheses."""
    outcome = _bundle_outcome("apd_2024_10k")
    targets = {h.hypothesized_parent for h in outcome.hypotheses}
    assert "us-gaap:EarningsPerShareBasic" not in targets
    assert not any("EffectiveIncomeTaxRate" in target for target in targets)
    assert all(
        h.hypothesis_type == "RESIDUAL_COMPONENT" and h.period
        for h in outcome.hypotheses
    )


def test_bac_2011_bundle_tax_recon_magnet_emits_nothing() -> None:
    """Verify the BAC 2011 tax-reconciliation magnet produces no hypotheses."""
    outcome = _bundle_outcome("bac_2011_10k")
    targets = {h.hypothesized_parent for h in outcome.hypotheses}
    assert "us-gaap:EffectiveIncomeTaxRateReconciliationTaxContingencies" not in targets
    assert not any("EffectiveIncomeTaxRate" in target for target in targets)


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

    assert len({semantic(f) for f in outcome.solved_facts}) == 24
    parent_contexts = {
        (f.instant_date, tuple(sorted(f.dimensions.items()))) for f in parent_facts
    }
    assert all(
        (f.instant_date, tuple(sorted(f.dimensions.items()))) in parent_contexts
        for f in outcome.solved_facts
    )
    undimensioned_assets = [
        q.fact
        for q in outcome.quarantined_facts
        if q.fact.concept_qname == _ASSETS and not q.fact.dimensions
    ]
    assert len(undimensioned_assets) == 2


def _undim_fact(acc: AccessionNumber, qname: str, value: float) -> XbrlFact:
    return XbrlFact(
        acc,
        qname,
        value,
        unit="USD",
        period_type="instant",
        instant_date="2024-12-31",
    )


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


def test_quarantine_reason_vocabulary_is_pinned() -> None:
    """Verify the pair-level reason vocabulary and the slim record shape."""
    assert QUARANTINE_REASONS == (
        "DIMENSIONED_ONLY_NO_CALC_ROLE",
        "DIMENSIONED_ONLY_IN_CALC_ARCS",
        "DIMENSIONED_ONLY_IN_CALC_ARCS_PARTIALLY_CONSUMED",
        "UNDIMENSIONED_NO_CALC_ROLE",
        "UNDIMENSIONED_IN_CALC_ARCS_NOT_CONSUMED",
        "UNDIMENSIONED_IN_CALC_ARCS_PARENT_NOT_AUDITED",
    )
    assert {field.name for field in fields(QuarantinedFact)} == {"fact", "reason"}


def _reason_by_concept(outcome) -> dict[str, str]:  # noqa: ANN001, ANN202
    return {q.fact.concept_qname: q.reason for q in outcome.quarantined_facts}


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


def test_cross_firm_rule_weight_discounting() -> None:
    """Verify intra-firm full weight vs cross-firm prior discounting."""
    rule = UnificationRule(
        rule_id="R_MSFT_CLOUD",
        target_node="us-gaap:Revenues",
        concept_qname="msft:CloudServicesRevenue",
        weight=1.0,
        scope=("MSFT", "Technology", "*"),
    )

    w_self = CounterSolver.evaluate_rule_weight(rule, firm="MSFT", sector="Technology")
    assert w_self == 1.0

    w_cross = CounterSolver.evaluate_rule_weight(
        rule, firm="GOOGL", sector="Technology"
    )
    assert w_cross == 0.5

    w_mismatch = CounterSolver.evaluate_rule_weight(rule, firm="XOM", sector="Energy")
    assert w_mismatch == 0.0
