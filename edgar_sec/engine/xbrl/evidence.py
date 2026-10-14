"""Scoped evidence knowledge base with 4-tier backoff and cryptographic freeze."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
import hashlib
import json
from typing import Any

from edgar_sec.engine.xbrl.domain import DomainTaxonomy, GeoHierarchyEdge
from edgar_sec.foundation.hashing import sha256_text


@dataclass(frozen=True, slots=True)
class UnificationRule:
    """Declarative concept unification rule with scope and empirical support counts."""

    rule_id: str
    target_node: str
    concept_qname: str
    weight: float = 1.0
    scope: tuple[str, str, str] = ("*", "*", "*")
    n_support: int = 1
    n_eligible: int = 1


@dataclass(slots=True)
class EvidenceKnowledgeBase:
    """Scoped knowledge base tracking rules, meronymy, and cryptographic freeze state."""

    taxonomy: DomainTaxonomy
    rules: list[UnificationRule] = field(default_factory=list)
    is_frozen: bool = False
    frozen_sha256: str | None = None
    _geo_parents: dict[str, set[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self._geo_parents and self.taxonomy.geography_edges:
            self._build_geo_index(self.taxonomy.geography_edges)

    def _build_geo_index(self, edges: Sequence[GeoHierarchyEdge]) -> None:
        for edge in edges:
            self._geo_parents.setdefault(edge.child_qname, set()).add(edge.parent_qname)

    def is_geo_subsumed(self, child: str, ancestor: str) -> bool:
        """Check if child node is topologically subsumed by ancestor in DAG."""
        if child == ancestor:
            return True
        visited: set[str] = set()
        queue = [child]
        while queue:
            curr = queue.pop(0)
            if curr in visited:
                continue
            visited.add(curr)
            parents = self._geo_parents.get(curr, set())
            if ancestor in parents:
                return True
            queue.extend(parents)
        return False

    @staticmethod
    def scope_specificity(
        scope: tuple[str, str, str],
        firm: str,
        sector: str,
        year: int | str,
    ) -> tuple[int, str]:
        """Compute 4-tier scope specificity score and human-readable tier label."""
        s_firm, s_sec, s_yr = scope
        yr_str = str(year)
        if s_firm not in ("*", firm):
            return 0, "TIER_MISMATCH"
        if s_sec not in ("*", sector):
            return 0, "TIER_MISMATCH"
        if s_yr not in ("*", yr_str):
            return 0, "TIER_MISMATCH"

        if s_firm == firm and s_sec == sector and s_yr == yr_str:
            return 4, "TIER_1_FIRM_SECTOR_YEAR"
        if s_firm == firm and s_sec == sector and s_yr == "*":
            return 3, "TIER_2_FIRM_SECTOR"
        if s_firm == "*" and s_sec == sector and s_yr == "*":
            return 2, "TIER_3_SECTOR"
        return 1, "TIER_4_UNIVERSAL"

    @staticmethod
    def laplace_confidence(n_support: int, n_eligible: int) -> float:
        """Compute Laplace smoothed empirical confidence (n + 1) / (N + 2)."""
        return round((n_support + 1.0) / (n_eligible + 2.0), 4)

    def add_rule(self, rule: UnificationRule) -> None:
        """Append a new unification rule if knowledge base is not frozen."""
        if self.is_frozen:
            raise RuntimeError(
                "cannot add rule: knowledge base is cryptographically frozen"
            )
        self.rules.append(rule)

    def freeze(self) -> str:
        """Lock knowledge base in read-only state and return SHA-256 seal."""
        sorted_repr = json.dumps(
            [
                {
                    "rule_id": r.rule_id,
                    "target": r.target_node,
                    "qname": r.concept_qname,
                    "weight": r.weight,
                    "scope": list(r.scope),
                    "support": r.n_support,
                    "eligible": r.n_eligible,
                }
                for r in sorted(self.rules, key=lambda x: x.rule_id)
            ],
            sort_keys=True,
        )
        self.is_frozen = True
        self.frozen_sha256 = sha256_text(sorted_repr)
        return self.frozen_sha256
