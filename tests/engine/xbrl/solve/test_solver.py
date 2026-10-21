"""Unit tests for XBRL constraint solver and multi-hop derivation."""

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.engine.xbrl.evidence.evidence import (
    EvidenceKnowledgeBase,
    UnificationRule,
)
from edgar_sec.engine.xbrl.schema.models import (
    CalculationArc,
    XbrlFact,
)
from edgar_sec.engine.xbrl.solve.solver import XbrlConstraintSolver
from edgar_sec.engine.xbrl.solve.antichain import CandidateRelation


def test_solve_placements_via_calc_arc_and_kb() -> None:
    """Verify solver placement determination via calc arcs and KB backoff."""
    tax = load_domain_taxonomy()
    kb = EvidenceKnowledgeBase(taxonomy=tax)
    kb.add_rule(
        UnificationRule(
            "R1",
            "us-gaap:GrossProfit",
            "msft:CustomDirectCost",
            weight=-1.0,
            scope=("*", "*", "*"),
        )
    )

    solver = XbrlConstraintSolver(kb)
    acc = AccessionNumber("0000950170-24-087843")
    facts = [
        XbrlFact(acc, "msft:DirectRevenue", 100.0),
        XbrlFact(acc, "msft:CustomDirectCost", 30.0),
        XbrlFact(acc, "msft:UnknownKPI", 5.0, unit="pure"),
    ]
    calc_arcs = [
        CalculationArc("us-gaap:GrossProfit", "msft:DirectRevenue", weight=1.0),
    ]

    preds = solver.solve_placements(facts, calc_arcs)
    assert len(preds) == 3

    p0 = next(p for p in preds if p.concept_qname == "msft:DirectRevenue")
    assert p0.predicted_parent == "us-gaap:GrossProfit"
    assert p0.predicted_weight == 1.0

    p1 = next(p for p in preds if p.concept_qname == "msft:CustomDirectCost")
    assert p1.predicted_parent == "us-gaap:GrossProfit"
    assert p1.predicted_weight == -1.0

    p2 = next(p for p in preds if p.concept_qname == "msft:UnknownKPI")
    assert p2.is_abstained


def test_evaluate_goal_derived_multi_hop() -> None:
    """Verify multi-hop derivation of GrossProfit from Revenue and COGS."""
    tax = load_domain_taxonomy()
    kb = EvidenceKnowledgeBase(taxonomy=tax)
    solver = XbrlConstraintSolver(kb)

    acc = AccessionNumber("0000950170-24-087843")
    facts = [
        XbrlFact(
            acc,
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            245122.0,
        ),
        XbrlFact(acc, "us-gaap:CostOfGoodsAndServicesSold", 75827.0),
    ]
    calc_arcs = [
        CalculationArc(
            "us-gaap:GrossProfit",
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            weight=1.0,
        ),
        CalculationArc(
            "us-gaap:GrossProfit",
            "us-gaap:CostOfGoodsAndServicesSold",
            weight=-1.0,
        ),
    ]

    goal = solver.evaluate_goal("us-gaap:GrossProfit", facts, calc_arcs)
    assert goal.computed_value == 169295.0
    assert goal.resolution_tier == "DERIVED_MULTI_HOP"
    assert not goal.is_direct


def test_breakdown_concept_dimensional_axis() -> None:
    """Verify decomposing a concept into member components along a dimensional axis."""
    tax = load_domain_taxonomy()
    solver = XbrlConstraintSolver(EvidenceKnowledgeBase(taxonomy=tax))
    acc = AccessionNumber("0000950170-24-087843")
    axis = "srt:ProductOrServiceAxis"
    facts = [
        XbrlFact(
            acc,
            "us-gaap:Revenues",
            97726.0,
            dimensions={axis: "msft:ServerProductsMember"},
        ),
        XbrlFact(
            acc,
            "us-gaap:Revenues",
            54875.0,
            dimensions={axis: "msft:OfficeProductsMember"},
        ),
        XbrlFact(
            acc, "us-gaap:Revenues", 23244.0, dimensions={axis: "msft:WindowsMember"}
        ),
        XbrlFact(acc, "us-gaap:Revenues", 175845.0),
    ]

    breakdown = solver.breakdown_concept("Revenues", facts, axis=axis)
    assert len(breakdown.components) == 3
    assert breakdown.total_value == 175845.0
    assert breakdown.is_balanced
    assert breakdown.discrepancy == 0.0

    goal = solver.evaluate_goal("Revenues", facts, axis_filter=axis)
    assert goal.computed_value == 175845.0
    assert goal.resolution_tier == "DIMENSIONAL_ANTICHAIN_SUM"
    assert goal.breakdown is not None


def test_evaluate_goal_subatomic_algebraic_identity() -> None:
    """Verify deriving missing GrossProfit and OperatingIncome via subatomic identities."""
    tax = load_domain_taxonomy()
    solver = XbrlConstraintSolver(EvidenceKnowledgeBase(taxonomy=tax))
    acc = AccessionNumber("0001652044-25-000014")
    facts = [
        XbrlFact(acc, "us-gaap:Revenues", 350018.0),
        XbrlFact(acc, "us-gaap:CostOfGoodsAndServicesSold", 146306.0),
        XbrlFact(acc, "us-gaap:OperatingExpenses", 91322.0),
    ]

    gp_goal = solver.evaluate_goal("GrossProfit", facts)
    assert gp_goal.computed_value == 203712.0
    assert gp_goal.resolution_tier == "SUBATOMIC_ALGEBRAIC_IDENTITY"

    op_goal = solver.evaluate_goal("OperatingIncomeLoss", facts)
    assert op_goal.computed_value == 112390.0
    assert op_goal.resolution_tier == "SUBATOMIC_ALGEBRAIC_IDENTITY"


def test_evaluate_goal_extended_accounting_identities() -> None:
    """Verify Assets, FreeCashFlow, ComprehensiveIncome, and LiabilitiesAndEquity identities."""
    tax = load_domain_taxonomy()
    solver = XbrlConstraintSolver(EvidenceKnowledgeBase(taxonomy=tax))
    acc = AccessionNumber("0000950170-24-087843")
    facts = [
        XbrlFact(acc, "us-gaap:AssetsCurrent", 159598.0),
        XbrlFact(acc, "us-gaap:AssetsNoncurrent", 352565.0),
        XbrlFact(acc, "us-gaap:Liabilities", 243686.0),
        XbrlFact(acc, "us-gaap:StockholdersEquity", 268477.0),
        XbrlFact(acc, "us-gaap:NetCashProvidedByUsedInOperatingActivities", 118548.0),
        XbrlFact(acc, "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment", 44477.0),
        XbrlFact(acc, "us-gaap:NetIncomeLoss", 88136.0),
        XbrlFact(acc, "us-gaap:OtherComprehensiveIncomeLossNetOfTax", 753.0),
    ]

    assets_goal = solver.evaluate_goal("Assets", facts)
    assert assets_goal.computed_value == 512163.0
    assert assets_goal.resolution_tier == "SUBATOMIC_ALGEBRAIC_IDENTITY"

    fcf_goal = solver.evaluate_goal("FreeCashFlow", facts)
    assert fcf_goal.computed_value == 74071.0
    assert fcf_goal.resolution_tier == "SUBATOMIC_ALGEBRAIC_IDENTITY"

    comp_goal = solver.evaluate_goal("ComprehensiveIncomeNet", facts)
    assert comp_goal.computed_value == 88889.0
    assert comp_goal.resolution_tier == "SUBATOMIC_ALGEBRAIC_IDENTITY"

    le_goal = solver.evaluate_goal("LiabilitiesAndStockholdersEquity", facts)
    assert le_goal.computed_value == 512163.0
    assert le_goal.resolution_tier == "SUBATOMIC_ALGEBRAIC_IDENTITY"


def test_classify_candidate_facts_verdict_model() -> None:
    """Verify 3-valued classification (ACCEPT/REJECT/UNKNOWN) and unknown priority."""
    tax = load_domain_taxonomy()
    solver = XbrlConstraintSolver(EvidenceKnowledgeBase(taxonomy=tax))
    acc = AccessionNumber("0000950170-24-087843")
    calc_arcs = [
        CalculationArc("us-gaap:GrossProfit", "us-gaap:Revenues", weight=1.0),
        CalculationArc("us-gaap:GrossProfit", "us-gaap:CostOfGoodsSold", weight=-1.0),
    ]
    facts = [
        XbrlFact(acc, "us-gaap:GrossProfit", 1000.0),
        XbrlFact(acc, "us-gaap:Revenues", 1500.0),
        XbrlFact(acc, "us-gaap:CostOfGoodsSold", 500.0),
        XbrlFact(acc, "us-gaap:PolicyNote", "prose text block", unit=None),
        XbrlFact(acc, "msft:UnrealizedGainLossExtension", 250.0),
    ]

    verdicts = solver.classify_candidate_facts("us-gaap:GrossProfit", facts, calc_arcs)
    assert len(verdicts) == 5

    v_root = next(v for v in verdicts if v.concept_qname == "us-gaap:GrossProfit")
    assert v_root.decision == "ACCEPT"
    assert v_root.role == "ROOT"

    v_rev = next(v for v in verdicts if v.concept_qname == "us-gaap:Revenues")
    assert v_rev.decision == "ACCEPT"
    assert v_rev.role == "LEAF"

    v_prose = next(v for v in verdicts if v.concept_qname == "us-gaap:PolicyNote")
    assert v_prose.decision == "REJECT"
    assert v_prose.reject_reason == "NON_NUMERIC_PROSE"

    v_unk = next(
        v for v in verdicts if v.concept_qname == "msft:UnrealizedGainLossExtension"
    )
    assert v_unk.decision == "UNKNOWN"
    assert v_unk.unknown_reason == "UNSEEN_SIGNATURE"
    assert v_unk.priority > 0.0


def test_evaluate_goal_basis_states() -> None:
    """Verify 6 basis outcomes (REPORTED_VERIFIED, REPORTED, DERIVED_EXACT, NOT_AVAILABLE)."""
    tax = load_domain_taxonomy()
    solver = XbrlConstraintSolver(EvidenceKnowledgeBase(taxonomy=tax))
    acc = AccessionNumber("0000950170-24-087843")
    calc_arcs = [
        CalculationArc("us-gaap:GrossProfit", "us-gaap:Revenues", weight=1.0),
        CalculationArc("us-gaap:GrossProfit", "us-gaap:CostOfGoodsSold", weight=-1.0),
    ]

    # 1. REPORTED_VERIFIED
    facts_verified = [
        XbrlFact(acc, "us-gaap:GrossProfit", 1000.0),
        XbrlFact(acc, "us-gaap:Revenues", 1500.0),
        XbrlFact(acc, "us-gaap:CostOfGoodsSold", 500.0),
    ]
    g_ver = solver.evaluate_goal("us-gaap:GrossProfit", facts_verified, calc_arcs)
    assert g_ver.basis == "REPORTED_VERIFIED"
    assert g_ver.value == 1000.0
    assert g_ver.residual == 0.0

    # 2. REPORTED (no child arcs)
    facts_rep = [XbrlFact(acc, "us-gaap:Revenues", 245122.0)]
    g_rep = solver.evaluate_goal("us-gaap:Revenues", facts_rep, ())
    assert g_rep.basis == "REPORTED"
    assert g_rep.value == 245122.0

    # 3. DERIVED_EXACT (missing root)
    facts_derived = [
        XbrlFact(acc, "us-gaap:Revenues", 1500.0),
        XbrlFact(acc, "us-gaap:CostOfGoodsSold", 500.0),
    ]
    g_der = solver.evaluate_goal("us-gaap:GrossProfit", facts_derived, calc_arcs)
    assert g_der.basis == "DERIVED_EXACT"
    assert g_der.value == 1000.0

    # 4. NOT_AVAILABLE
    g_na = solver.evaluate_goal("us-gaap:UnknownConcept", facts_rep, ())
    assert g_na.basis == "NOT_AVAILABLE"
    assert g_na.value is None


def test_subatomic_algebraic_derivation_gross_profit() -> None:
    """Verify GrossProfit derived from Revenue and COGS via atom relations."""
    tax = load_domain_taxonomy()
    solver = XbrlConstraintSolver(EvidenceKnowledgeBase(taxonomy=tax))
    acc = AccessionNumber("0000950170-24-087843")
    facts = [
        XbrlFact(
            acc, "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 50000.0
        ),
        XbrlFact(acc, "us-gaap:CostOfGoodsSold", 30000.0),
    ]
    gp_goal = solver.evaluate_goal("GrossProfit", facts)
    assert gp_goal.value == 20000.0
    assert gp_goal.basis == "DERIVED_EXACT"
    assert gp_goal.resolution_tier == "SUBATOMIC_ALGEBRAIC_IDENTITY"


def test_uk_vs_eu_antichain_geography_cut() -> None:
    """Verify UK and EU are disjoint peers, pruning subsumed Germany to prevent double counting."""
    tax = load_domain_taxonomy()
    kb = EvidenceKnowledgeBase(taxonomy=tax)
    solver = XbrlConstraintSolver(kb)
    acc = AccessionNumber("0000950170-24-087843")
    axis = "us-gaap:StatementGeographicalAxis"
    facts = [
        XbrlFact(
            acc,
            "us-gaap:Revenues",
            60000.0,
            dimensions={axis: "srt:EuropeanUnionMember"},
        ),
        XbrlFact(acc, "us-gaap:Revenues", 40000.0, dimensions={axis: "country:GB"}),
        XbrlFact(acc, "us-gaap:Revenues", 20000.0, dimensions={axis: "country:DE"}),
    ]

    breakdown = solver.breakdown_concept("Revenues", facts, axis=axis)
    comp_ids = {c.identifier for c in breakdown.components}
    assert "country:DE" not in comp_ids
    assert "srt:EuropeanUnionMember" in comp_ids
    assert "country:GB" in comp_ids

    goal = solver.evaluate_goal("Revenues", facts, axis_filter=axis)
    assert goal.computed_value == 100000.0
    assert goal.resolution_tier == "DIMENSIONAL_ANTICHAIN_SUM"


def test_subatomic_algebraic_derivation_derivative_net_asset() -> None:
    """Verify DerivativeAssetsNet derived from Gross, Netting, and Collateral."""
    tax = load_domain_taxonomy()
    solver = XbrlConstraintSolver(EvidenceKnowledgeBase(taxonomy=tax))
    acc = AccessionNumber("0000950170-24-087843")
    facts = [
        XbrlFact(acc, "us-gaap:DerivativeAssetsGross", 50000.0),
        XbrlFact(acc, "us-gaap:DerivativeAssetFairValueOffsetAgainstNetting", 15000.0),
        XbrlFact(
            acc, "us-gaap:DerivativeAssetFairValueOffsetAgainstCollateral", 5000.0
        ),
    ]
    net_goal = solver.evaluate_goal("DerivativeAssetsNet", facts)
    assert net_goal.value == 30000.0
    assert net_goal.basis == "DERIVED_EXACT"
    assert net_goal.resolution_tier == "SUBATOMIC_ALGEBRAIC_IDENTITY"


def test_solver_rejects_double_counting_and_keeps_violation_trace() -> None:
    tax = load_domain_taxonomy()
    solver = XbrlConstraintSolver(EvidenceKnowledgeBase(taxonomy=tax))
    acc = AccessionNumber("0000950170-24-087843")
    facts = [
        XbrlFact(acc, "us-gaap:AssetsCurrent", 10.0),
        XbrlFact(acc, "us-gaap:CashAndCashEquivalentsAtCarryingValue", 7.0),
    ]
    arcs = [
        CalculationArc("us-gaap:Assets", "us-gaap:AssetsCurrent", 1.0),
        CalculationArc(
            "us-gaap:Assets", "us-gaap:CashAndCashEquivalentsAtCarryingValue", 1.0
        ),
        CalculationArc(
            "us-gaap:AssetsCurrent",
            "us-gaap:CashAndCashEquivalentsAtCarryingValue",
            1.0,
        ),
    ]

    aggregate = solver.evaluate_goal("us-gaap:Assets", facts, arcs)
    assert aggregate.value is None
    assert aggregate.basis == "CONFLICT_DOUBLE_COUNTING"
    assert aggregate.resolution_tier == "ANTICHAIN_CONFLICT"
    assert any("AssetsCurrent" in trace for trace in aggregate.derivation_path)
    assert any("CashAndCashEquivalents" in trace for trace in aggregate.derivation_path)


def test_solver_resolves_candidate_frontier_for_broad_income_query() -> None:
    tax = load_domain_taxonomy()
    solver = XbrlConstraintSolver(EvidenceKnowledgeBase(taxonomy=tax))
    acc = AccessionNumber("0000950170-24-087843")
    facts = [
        XbrlFact(acc, "us-gaap:NetIncomeLoss", 88_136.0),
        XbrlFact(acc, "us-gaap:OperatingIncomeLoss", 109_433.0),
        XbrlFact(acc, "us-gaap:NonoperatingIncomeExpense", 2_000.0),
    ]
    arcs = [
        CalculationArc("us-gaap:NetIncomeLoss", "us-gaap:OperatingIncomeLoss", 1.0),
        CalculationArc(
            "us-gaap:NetIncomeLoss", "us-gaap:NonoperatingIncomeExpense", 1.0
        ),
    ]

    frontier = solver.resolve_query_frontier("Income", facts, arcs)
    assert len(frontier.candidates) == 3
    relations = {
        frozenset((pair.concept_a, pair.concept_b)): pair.relation
        for pair in frontier.pairwise_relations
    }
    assert (
        relations[frozenset(("us-gaap:NetIncomeLoss", "us-gaap:OperatingIncomeLoss"))]
        == CandidateRelation.ANCESTOR_DESCENDANT_OVERLAP
    )
    assert (
        relations[
            frozenset(
                ("us-gaap:OperatingIncomeLoss", "us-gaap:NonoperatingIncomeExpense")
            )
        ]
        == CandidateRelation.DISJOINT_SIBLING
    )


def test_retail_costs_and_operating_income_relations_compose() -> None:
    tax = load_domain_taxonomy()
    solver = XbrlConstraintSolver(EvidenceKnowledgeBase(taxonomy=tax))
    acc = AccessionNumber("0000950170-24-087843")
    facts = [
        XbrlFact(
            acc,
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            100.0,
        ),
        XbrlFact(acc, "retail:CostOfSales", 10.0),
        XbrlFact(acc, "retail:FulfillmentExpenses", 2.0),
        XbrlFact(acc, "retail:TechnologyAndInfrastructure", 1.0),
        XbrlFact(acc, "retail:SalesAndMarketingExpense", 3.0),
        XbrlFact(acc, "retail:GeneralAndAdministrativeExpense", 4.0),
    ]

    costs = solver.evaluate_goal("CostsAndExpenses", facts)
    operating_income = solver.evaluate_goal("OperatingIncome", facts)
    assert costs.value == 20.0
    assert costs.resolution_tier == "SUBATOMIC_ALGEBRAIC_IDENTITY"
    assert operating_income.value == 80.0
    assert operating_income.resolution_tier == "SUBATOMIC_ALGEBRAIC_IDENTITY"
