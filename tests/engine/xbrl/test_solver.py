"""Unit tests for XBRL constraint solver and multi-hop derivation."""

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.domain import load_domain_taxonomy
from edgar_sec.engine.xbrl.evidence import (
    EvidenceKnowledgeBase,
    UnificationRule,
)
from edgar_sec.engine.xbrl.models import (
    CalculationArc,
    XbrlFact,
)
from edgar_sec.engine.xbrl.solver import XbrlConstraintSolver


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
