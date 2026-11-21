"""Anti-chain verification and query frontier analysis for XBRL linkbase DAGs."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any


class CandidateRelation(str, Enum):
    """Algebraic graph relationship between candidate financial concepts."""

    ANCESTOR_DESCENDANT_OVERLAP = "ANCESTOR_DESCENDANT_OVERLAP"
    DISJOINT_SIBLING = "DISJOINT_SIBLING"
    VALUATION_NETTING = "VALUATION_NETTING"
    EQUAL = "EQUAL"


@dataclass(frozen=True, slots=True)
class AntiChainOutcome:
    """Outcome of mathematical anti-chain verification over financial nodes."""

    is_valid: bool
    computed_sum: float
    target_value: float
    discrepancy: float
    violations: tuple[str, ...]
    selected_concepts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandidateFrontierPair:
    """Pairwise algebraic relationship between two candidate frontier nodes."""

    concept_a: str
    concept_b: str
    relation: CandidateRelation
    explanation: str


@dataclass(frozen=True, slots=True)
class CandidateFrontier:
    """Candidate solutions frontier for underspecified or broad queries."""

    root_query: str
    candidates: tuple[dict[str, Any], ...]
    pairwise_relations: tuple[CandidateFrontierPair, ...]


class AntiChainValidator:
    """Validates partition non-double-counting and resolves query frontiers."""

    @staticmethod
    def build_reachability_map(
        calculation_arcs: Sequence[tuple[str, str, float]],
    ) -> dict[str, set[str]]:
        """Build transitive closure mapping each parent to all reachable descendants."""
        children_map: dict[str, set[str]] = {}
        all_nodes: set[str] = set()
        for parent, child, _ in calculation_arcs:
            children_map.setdefault(parent, set()).add(child)
            all_nodes.add(parent)
            all_nodes.add(child)

        reachability: dict[str, set[str]] = {}
        for node in all_nodes:
            descendants: set[str] = set()
            frontier = list(children_map.get(node, ()))
            while frontier:
                curr = frontier.pop()
                if curr not in descendants:
                    descendants.add(curr)
                    frontier.extend(children_map.get(curr, ()))
            reachability[node] = descendants
        return reachability

    def verify_non_double_counting(
        self,
        selected_concepts: Sequence[str],
        calculation_arcs: Sequence[tuple[str, str, float]],
        target_concept: str | None = None,
        concept_values: dict[str, float] | None = None,
        concept_weights: dict[str, float] | None = None,
    ) -> AntiChainOutcome:
        """Prove that no two selected concepts share an ancestor-descendant edge."""
        reachability = self.build_reachability_map(calculation_arcs)
        violations: list[str] = []
        selected_list = list(selected_concepts)

        for i, a in enumerate(selected_list):
            for b in selected_list[i + 1 :]:
                if b in reachability.get(a, set()):
                    violations.append(
                        f"Double-counting: '{a}' is an ancestor of '{b}' in calculation DAG"
                    )
                elif a in reachability.get(b, set()):
                    violations.append(
                        f"Double-counting: '{b}' is an ancestor of '{a}' in calculation DAG"
                    )

        target_val = 0.0
        if target_concept and concept_values and target_concept in concept_values:
            target_val = concept_values[target_concept]

        computed = 0.0
        if concept_values:
            weights = concept_weights or {}
            for c in selected_list:
                w = weights.get(c, 1.0)
                computed += w * concept_values.get(c, 0.0)

        discrepancy = abs(computed - target_val) if target_concept is not None else 0.0
        is_valid = len(violations) == 0 and discrepancy < 1.0

        return AntiChainOutcome(
            is_valid=is_valid,
            computed_sum=computed,
            target_value=target_val,
            discrepancy=discrepancy,
            violations=tuple(violations),
            selected_concepts=tuple(selected_list),
        )

    def classify_pair_relation(
        self,
        concept_a: str,
        concept_b: str,
        reachability: dict[str, set[str]],
        contra_concepts: set[str] | None = None,
    ) -> tuple[CandidateRelation, str]:
        """Classify pairwise relation as overlap, netting, or disjoint sibling."""
        if concept_a == concept_b:
            return CandidateRelation.EQUAL, "Identical concept coordinates"

        if concept_b in reachability.get(concept_a, set()):
            return (
                CandidateRelation.ANCESTOR_DESCENDANT_OVERLAP,
                f"'{concept_a}' is an aggregate parent of '{concept_b}'; combining violates anti-chain",
            )
        if concept_a in reachability.get(concept_b, set()):
            return (
                CandidateRelation.ANCESTOR_DESCENDANT_OVERLAP,
                f"'{concept_b}' is an aggregate parent of '{concept_a}'; combining violates anti-chain",
            )

        contras = contra_concepts or set()
        if concept_a in contras or concept_b in contras:
            return (
                CandidateRelation.VALUATION_NETTING,
                f"'{concept_a}' and '{concept_b}' form a contra netting dual pair",
            )

        return (
            CandidateRelation.DISJOINT_SIBLING,
            f"'{concept_a}' and '{concept_b}' are mutually disjoint sibling branches",
        )

    def resolve_query_frontier(
        self,
        query_concept: str,
        candidate_facts: Sequence[dict[str, Any]],
        calculation_arcs: Sequence[tuple[str, str, float]],
        contra_concepts: set[str] | None = None,
    ) -> CandidateFrontier:
        """Resolve candidate answers and compute pairwise algebraic relations."""
        reachability = self.build_reachability_map(calculation_arcs)
        q_clean = query_concept.lower()
        matching = [
            f for f in candidate_facts if q_clean in f.get("concept_qname", "").lower()
        ]

        pairs: list[CandidateFrontierPair] = []
        for i, f_a in enumerate(matching):
            name_a = f_a["concept_qname"]
            for f_b in matching[i + 1 :]:
                name_b = f_b["concept_qname"]
                rel, expl = self.classify_pair_relation(
                    name_a, name_b, reachability, contra_concepts
                )
                pairs.append(
                    CandidateFrontierPair(
                        concept_a=name_a,
                        concept_b=name_b,
                        relation=rel,
                        explanation=expl,
                    )
                )

        return CandidateFrontier(
            root_query=query_concept,
            candidates=tuple(matching),
            pairwise_relations=tuple(pairs),
        )

    def render_ascii_tree(
        self,
        root_concept: str,
        components: Sequence[dict[str, Any]],
        target_value: float | None = None,
        is_valid: bool = True,
    ) -> str:
        """Render human-inspectable decomposition tree with weights and equations."""
        target_str = (
            f"${target_value:,.0f}" if target_value is not None else "UNSPECIFIED"
        )
        lines = [f"Target Root: {root_concept} = {target_str}"]
        computed_sum = 0.0

        for comp in components:
            weight = comp.get("weight", 1.0)
            val = comp.get("value", 0.0)
            sign = "+" if weight > 0 else "-"
            concept = comp.get("concept", "unknown")
            lines.append(f"  └── [{sign}] {concept}: ${val:,.0f}")
            computed_sum += weight * val

        status = "VERIFIED" if is_valid else "VIOLATED (Double-Counting)"
        disc = abs(computed_sum - target_value) if target_value is not None else 0.0
        lines.append(
            f"Result Sum: ${computed_sum:,.0f} (discrepancy: {disc:.1f}) | Anti-Chain Invariant: {status}"
        )
        return "\n".join(lines)

    def render_candidate_frontier_ascii(self, frontier: CandidateFrontier) -> str:
        """Render candidate frontier with pairwise overlap and disjointness relations."""
        lines = [
            f"Candidate Query Frontier for '{frontier.root_query}' ({len(frontier.candidates)} candidates):"
        ]
        for c in frontier.candidates:
            val = c.get("numeric_value", 0.0)
            lines.append(f"  • {c['concept_qname']}: ${val:,.0f}")

        if frontier.pairwise_relations:
            lines.append("\nPairwise Graph Relations:")
            for p in frontier.pairwise_relations:
                lines.append(f"  [{p.relation.value}] {p.concept_a} <--> {p.concept_b}")
                lines.append(f"      └── {p.explanation}")

        return "\n".join(lines)
