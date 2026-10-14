"""Constraint-satisfaction graph solver and multi-hop financial derivation engine."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from edgar_sec.engine.xbrl.decomposer import infer_semantic_frame
from edgar_sec.engine.xbrl.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.gold import PlacementPrediction
from edgar_sec.engine.xbrl.models import (
    CalculationArc,
    PresentationArc,
    XbrlFact,
)


@dataclass(frozen=True, slots=True)
class GranularComponent:
    """Constituent component in a financial concept breakdown."""

    identifier: str
    value: float
    weight: float = 1.0
    member_dimension: str | None = None
    is_direct: bool = True


@dataclass(frozen=True, slots=True)
class ConceptBreakdown:
    """Granular breakdown of a financial concept into constituent parts."""

    target_concept: str
    total_value: float | None
    components: tuple[GranularComponent, ...]
    is_balanced: bool = True
    discrepancy: float = 0.0


@dataclass(frozen=True, slots=True)
class SolvedGoal:
    """Evaluated financial target value with provenance and derivation path."""

    target_concept: str
    computed_value: float | None
    resolution_tier: str
    derivation_path: tuple[str, ...] = ()
    confidence: float = 1.0
    is_direct: bool = False
    breakdown: ConceptBreakdown | None = None


class XbrlConstraintSolver:
    """Graph solver reconciling XBRL facts, calculation linkbases, and declarative rules."""

    def __init__(
        self,
        kb: EvidenceKnowledgeBase,
        *,
        enable_head_induction: bool = True,
    ) -> None:
        self.kb = kb
        self.enable_head_induction = enable_head_induction

    def solve_placements(
        self,
        facts: Sequence[XbrlFact],
        calculation_arcs: Sequence[CalculationArc],
        *,
        firm: str = "",
        sector: str = "",
        year: int | str = "",
    ) -> tuple[PlacementPrediction, ...]:
        """Determine target parent node and algebraic weight for extension facts."""
        calc_parents: dict[str, tuple[str, float]] = {
            arc.child_qname: (arc.parent_qname, arc.weight) for arc in calculation_arcs
        }
        predictions: list[PlacementPrediction] = []

        for fact in facts:
            qname = fact.concept_qname
            # 1. Check published calculation arc
            if qname in calc_parents:
                parent, weight = calc_parents[qname]
                predictions.append(
                    PlacementPrediction(
                        concept_qname=qname,
                        predicted_parent=parent,
                        predicted_weight=weight,
                        is_abstained=False,
                    )
                )
                continue

            # 2. Check KB unification rules with 4-tier scope backoff
            best_rule = None
            best_spec = 0
            for rule in self.kb.rules:
                if rule.concept_qname == qname:
                    spec, _ = self.kb.scope_specificity(rule.scope, firm, sector, year)
                    if spec > best_spec:
                        best_spec = spec
                        best_rule = rule

            if best_rule is not None:
                predictions.append(
                    PlacementPrediction(
                        concept_qname=qname,
                        predicted_parent=best_rule.target_node,
                        predicted_weight=best_rule.weight,
                        is_abstained=False,
                    )
                )
                continue

            # 3. Subatomic prime head induction
            if self.enable_head_induction:
                frame = infer_semantic_frame(
                    qname,
                    self.kb.taxonomy,
                    unit=fact.unit,
                    balance=fact.balance,
                )
                if frame.prime_head == "H_REVENUE":
                    predictions.append(
                        PlacementPrediction(
                            concept_qname=qname,
                            predicted_parent="us-gaap:GrossProfit",
                            predicted_weight=1.0,
                        )
                    )
                    continue
                if frame.prime_head == "H_COST":
                    predictions.append(
                        PlacementPrediction(
                            concept_qname=qname,
                            predicted_parent="us-gaap:GrossProfit",
                            predicted_weight=-1.0,
                        )
                    )
                    continue
                if frame.prime_head == "H_EXPENSE":
                    predictions.append(
                        PlacementPrediction(
                            concept_qname=qname,
                            predicted_parent="us-gaap:OperatingIncomeLoss",
                            predicted_weight=-1.0,
                        )
                    )
                    continue

            # 4. Abstain if unresolvable
            predictions.append(
                PlacementPrediction(
                    concept_qname=qname,
                    predicted_parent=None,
                    predicted_weight=None,
                    is_abstained=True,
                )
            )

        return tuple(predictions)

    def breakdown_concept(
        self,
        target_concept: str,
        facts: Sequence[XbrlFact],
        calculation_arcs: Sequence[CalculationArc] = (),
        *,
        axis: str | None = None,
    ) -> ConceptBreakdown:
        """Decompose a financial concept into granular components via axis or calculation arcs."""
        target_local = (
            target_concept.split(":")[-1] if ":" in target_concept else target_concept
        )

        if axis is not None:
            axis_local = axis.split(":")[-1] if ":" in axis else axis
            components: list[GranularComponent] = []
            for f in facts:
                c_local = (
                    f.concept_qname.split(":")[-1]
                    if ":" in f.concept_qname
                    else f.concept_qname
                )
                if c_local == target_local and f.dimensions:
                    for d_axis, d_member in f.dimensions.items():
                        d_axis_local = (
                            d_axis.split(":")[-1] if ":" in d_axis else d_axis
                        )
                        if d_axis_local == axis_local and isinstance(
                            f.value, (int, float)
                        ):
                            components.append(
                                GranularComponent(
                                    identifier=d_member,
                                    value=float(f.value),
                                    weight=1.0,
                                    member_dimension=d_axis,
                                )
                            )

            top_val = None
            for f in facts:
                c_local = (
                    f.concept_qname.split(":")[-1]
                    if ":" in f.concept_qname
                    else f.concept_qname
                )
                if (
                    c_local == target_local
                    and not f.dimensions
                    and isinstance(f.value, (int, float))
                ):
                    top_val = float(f.value)
                    break

            comp_sum = sum(c.value * c.weight for c in components)
            discrepancy = (
                round(abs(comp_sum - top_val), 4) if top_val is not None else 0.0
            )
            is_balanced = top_val is None or discrepancy < 1.0
            return ConceptBreakdown(
                target_concept=target_concept,
                total_value=top_val,
                components=tuple(components),
                is_balanced=is_balanced,
                discrepancy=discrepancy,
            )

        child_arcs = [
            a
            for a in calculation_arcs
            if (
                a.parent_qname == target_concept
                or a.parent_qname.split(":")[-1] == target_local
            )
        ]
        calc_components: list[GranularComponent] = []
        fact_map = {
            f.concept_qname: float(f.value)
            for f in facts
            if not f.dimensions and isinstance(f.value, (int, float))
        }
        local_fact_map = {
            f.concept_qname.split(":")[-1]: float(f.value)
            for f in facts
            if not f.dimensions and isinstance(f.value, (int, float))
        }

        for arc in child_arcs:
            c_q = arc.child_qname
            c_loc = c_q.split(":")[-1]
            val = fact_map.get(c_q, local_fact_map.get(c_loc))
            if val is not None:
                calc_components.append(
                    GranularComponent(
                        identifier=c_q,
                        value=val,
                        weight=arc.weight,
                    )
                )

        top_val = fact_map.get(target_concept, local_fact_map.get(target_local))
        comp_sum = sum(c.value * c.weight for c in calc_components)
        discrepancy = round(abs(comp_sum - top_val), 4) if top_val is not None else 0.0
        is_balanced = top_val is None or discrepancy < 1.0

        return ConceptBreakdown(
            target_concept=target_concept,
            total_value=top_val,
            components=tuple(calc_components),
            is_balanced=is_balanced,
            discrepancy=discrepancy,
        )

    def evaluate_goal(
        self,
        target_concept: str,
        facts: Sequence[XbrlFact],
        calculation_arcs: Sequence[CalculationArc] = (),
        *,
        axis_filter: str | None = None,
    ) -> SolvedGoal:
        """Evaluate a financial concept directly, via dimensional sum, or multi-hop roll-up."""
        if axis_filter is not None:
            bd = self.breakdown_concept(
                target_concept, facts, calculation_arcs, axis=axis_filter
            )
            if bd.components:
                total = sum(c.value * c.weight for c in bd.components)
                path = tuple(f"{c.identifier}={c.value}" for c in bd.components)
                return SolvedGoal(
                    target_concept=target_concept,
                    computed_value=round(total, 4),
                    resolution_tier="DIMENSIONAL_ANTICHAIN_SUM",
                    derivation_path=path,
                    breakdown=bd,
                )

        target_local = (
            target_concept.split(":")[-1] if ":" in target_concept else target_concept
        )
        fact_vals: dict[str, float] = {
            f.concept_qname: float(f.value)
            for f in facts
            if not f.dimensions and isinstance(f.value, (int, float))
        }
        local_fact_vals: dict[str, float] = {
            f.concept_qname.split(":")[-1]: float(f.value)
            for f in facts
            if not f.dimensions and isinstance(f.value, (int, float))
        }

        # 1. Direct fact match
        if target_concept in fact_vals:
            return SolvedGoal(
                target_concept=target_concept,
                computed_value=fact_vals[target_concept],
                resolution_tier="DIRECT_ANCHOR",
                is_direct=True,
            )
        if target_local in local_fact_vals:
            return SolvedGoal(
                target_concept=target_concept,
                computed_value=local_fact_vals[target_local],
                resolution_tier="DIRECT_ANCHOR",
                is_direct=True,
            )

        # 2. Multi-hop derivation via calculation arcs
        child_arcs = [
            a
            for a in calculation_arcs
            if a.parent_qname == target_concept
            or a.parent_qname.split(":")[-1] == target_local
        ]
        if child_arcs:
            total = 0.0
            path: list[str] = []
            all_resolved = True
            for arc in child_arcs:
                val = fact_vals.get(
                    arc.child_qname,
                    local_fact_vals.get(arc.child_qname.split(":")[-1]),
                )
                if val is not None:
                    total += val * arc.weight
                    path.append(f"{arc.child_qname} * {arc.weight}")
                else:
                    all_resolved = False
                    break
            if all_resolved and path:
                bd = self.breakdown_concept(target_concept, facts, calculation_arcs)
                return SolvedGoal(
                    target_concept=target_concept,
                    computed_value=round(total, 4),
                    resolution_tier="DERIVED_MULTI_HOP",
                    derivation_path=tuple(path),
                    is_direct=False,
                    breakdown=bd,
                )

        # 3. Cross-root algebraic derivation (subatomic identities)
        if target_local in ("GrossProfit", "GrossMargin"):
            rev = local_fact_vals.get("Revenues") or local_fact_vals.get(
                "RevenueFromContractWithCustomerExcludingAssessedTax"
            )
            cogs = (
                local_fact_vals.get("CostOfGoodsAndServicesSold")
                or local_fact_vals.get("CostOfGoodsSold")
                or local_fact_vals.get("CostOfRevenue")
            )
            if rev is not None and cogs is not None:
                gp = rev - cogs
                return SolvedGoal(
                    target_concept=target_concept,
                    computed_value=round(gp, 4),
                    resolution_tier="SUBATOMIC_ALGEBRAIC_IDENTITY",
                    derivation_path=(f"Revenues({rev}) - COGS({cogs})",),
                )

        if target_local in ("OperatingIncomeLoss", "OperatingIncome"):
            gp_goal = self.evaluate_goal("GrossProfit", facts, calculation_arcs)
            op_exp = local_fact_vals.get("OperatingExpenses")
            if gp_goal.computed_value is not None and op_exp is not None:
                op_inc = gp_goal.computed_value - op_exp
                return SolvedGoal(
                    target_concept=target_concept,
                    computed_value=round(op_inc, 4),
                    resolution_tier="SUBATOMIC_ALGEBRAIC_IDENTITY",
                    derivation_path=(
                        f"GrossProfit({gp_goal.computed_value}) - OpEx({op_exp})",
                    ),
                )

        if target_local in ("Assets", "AssetsTotal"):
            cur = local_fact_vals.get("AssetsCurrent")
            noncur = local_fact_vals.get("AssetsNoncurrent")
            if cur is not None and noncur is not None:
                total_assets = cur + noncur
                return SolvedGoal(
                    target_concept=target_concept,
                    computed_value=round(total_assets, 4),
                    resolution_tier="SUBATOMIC_ALGEBRAIC_IDENTITY",
                    derivation_path=(
                        f"AssetsCurrent({cur}) + AssetsNoncurrent({noncur})",
                    ),
                )
            liab = local_fact_vals.get("Liabilities")
            equity = local_fact_vals.get("StockholdersEquity") or local_fact_vals.get(
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"
            )
            if liab is not None and equity is not None:
                total_assets = liab + equity
                return SolvedGoal(
                    target_concept=target_concept,
                    computed_value=round(total_assets, 4),
                    resolution_tier="SUBATOMIC_ALGEBRAIC_IDENTITY",
                    derivation_path=(f"Liabilities({liab}) + Equity({equity})",),
                )

        if target_local in ("FreeCashFlow", "FCF"):
            ocf = local_fact_vals.get("OperatingCashFlow") or local_fact_vals.get(
                "NetCashProvidedByUsedInOperatingActivities"
            )
            capex = (
                local_fact_vals.get("CapitalExpenditures")
                or local_fact_vals.get("PaymentsToAcquirePropertyPlantAndEquipment")
                or local_fact_vals.get("PaymentsToAcquireProductiveAssets")
            )
            if ocf is not None and capex is not None:
                fcf = ocf - abs(capex)
                return SolvedGoal(
                    target_concept=target_concept,
                    computed_value=round(fcf, 4),
                    resolution_tier="SUBATOMIC_ALGEBRAIC_IDENTITY",
                    derivation_path=(f"OCF({ocf}) - CapEx({capex})",),
                )

        if target_local in ("ComprehensiveIncomeNet", "ComprehensiveIncome"):
            ni = local_fact_vals.get("NetIncomeLoss") or local_fact_vals.get(
                "NetIncome"
            )
            oci = local_fact_vals.get(
                "OtherComprehensiveIncomeLossNetOfTax"
            ) or local_fact_vals.get("OtherComprehensiveIncomeLoss")
            if ni is not None and oci is not None:
                comp = ni + oci
                return SolvedGoal(
                    target_concept=target_concept,
                    computed_value=round(comp, 4),
                    resolution_tier="SUBATOMIC_ALGEBRAIC_IDENTITY",
                    derivation_path=(f"NetIncome({ni}) + OCI({oci})",),
                )

        if target_local in ("LiabilitiesAndStockholdersEquity",):
            liab = local_fact_vals.get("Liabilities")
            equity = local_fact_vals.get("StockholdersEquity")
            if liab is not None and equity is not None:
                total_le = liab + equity
                return SolvedGoal(
                    target_concept=target_concept,
                    computed_value=round(total_le, 4),
                    resolution_tier="SUBATOMIC_ALGEBRAIC_IDENTITY",
                    derivation_path=(f"Liabilities({liab}) + Equity({equity})",),
                )

        return SolvedGoal(
            target_concept=target_concept,
            computed_value=None,
            resolution_tier="UNRESOLVED",
        )
