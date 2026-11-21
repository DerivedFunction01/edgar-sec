"""Shared specimens for the CounterSolver audit suites."""

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.schema.models import (
    AggregateFact,
    CalculationArc,
    ConceptBreakdown,
    ConceptDeclaration,
    GranularComponent,
    XbrlFact,
)


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


def _decls(*qnames: str, item_type: str = "xbrli:monetaryItemType") -> dict:
    return {
        qname: ConceptDeclaration(qname, qname.split(":")[-1], item_type=item_type)
        for qname in qnames
    }


def _undim_fact(acc: AccessionNumber, qname: str, value: float) -> XbrlFact:
    return XbrlFact(
        acc,
        qname,
        value,
        unit="USD",
        period_type="instant",
        instant_date="2024-12-31",
    )


def _reason_by_concept(outcome) -> dict[str, str]:  # noqa: ANN001, ANN202
    return {q.fact.concept_qname: q.reason for q in outcome.quarantined_facts}
