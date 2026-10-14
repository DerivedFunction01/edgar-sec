"""Empirical XBRL phrase collocation mining, support counting, and polarity CSP."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
import math

from edgar_sec.engine.xbrl.models import CalculationArc


@dataclass(frozen=True, slots=True)
class CandidatePhrase:
    """Discovered multi-token accounting phrase with empirical evidence scores."""

    phrase: tuple[str, ...]
    frequency: int
    pmi: float
    firm_count: int
    sic_count: int
    scope: str  # UNIVERSAL | SECTOR | FIRM


@dataclass(frozen=True, slots=True)
class CandidateRelation:
    """Discovered accounting relation between concepts with algebraic weight."""

    source_concept: str
    target_concept: str
    algebraic_weight: float
    relation_type: str  # PART_OF | CONTRA_OF
    formula_id: str | None = None
    firm_count: int = 1
    sic_count: int = 1
    scope: str = "FIRM"


class SupportCounter:
    """Aggregates occurrence counts across distinct firms and SIC industry groups."""

    def __init__(self) -> None:
        self._firm_occurrences: dict[tuple[str, ...], set[str]] = {}
        self._sic_occurrences: dict[tuple[str, ...], set[str]] = {}

    def observe(self, key: tuple[str, ...], firm: str, sic: str) -> None:
        """Record an occurrence of an item for a given firm and SIC."""
        if firm:
            self._firm_occurrences.setdefault(key, set()).add(firm)
        if sic:
            self._sic_occurrences.setdefault(key, set()).add(str(sic))

    def firm_count(self, key: tuple[str, ...]) -> int:
        """Count of distinct firms exhibiting the item."""
        return len(self._firm_occurrences.get(key, ()))

    def sic_count(self, key: tuple[str, ...]) -> int:
        """Count of distinct SIC codes exhibiting the item."""
        return len(self._sic_occurrences.get(key, ()))

    def classify_scope(self, key: tuple[str, ...]) -> str:
        """Determine universal, sector, or firm specificity tier."""
        n_firms = self.firm_count(key)
        n_sics = self.sic_count(key)
        if n_firms >= 2 and n_sics >= 2:
            return "UNIVERSAL"
        if n_firms >= 2:
            return "SECTOR"
        return "FIRM"


class CollocationMiner:
    """Mines recurrent phrases from CamelCase token sequences using PMI."""

    def __init__(
        self,
        *,
        min_pmi: float = 0.5,
        min_freq: int = 2,
    ) -> None:
        self.min_pmi = min_pmi
        self.min_freq = min_freq

    def mine_bigrams(
        self,
        token_sequences: Iterable[Sequence[str]],
        support: SupportCounter | None = None,
    ) -> list[CandidatePhrase]:
        """Extract adjacent token pairs exceeding PMI and frequency thresholds."""
        unigrams: Counter[str] = Counter()
        bigrams: Counter[tuple[str, str]] = Counter()
        total_bigrams = 0

        seq_list = list(token_sequences)
        for seq in seq_list:
            for tok in seq:
                unigrams[tok] += 1
            for i in range(len(seq) - 1):
                bg = (seq[i], seq[i + 1])
                bigrams[bg] += 1
                total_bigrams += 1

        if total_bigrams == 0:
            return []

        total_unigrams = sum(unigrams.values())
        candidates: list[CandidatePhrase] = []

        for bg, freq in bigrams.items():
            if freq < self.min_freq:
                continue
            p_bg = freq / total_bigrams
            p_t1 = unigrams[bg[0]] / total_unigrams
            p_t2 = unigrams[bg[1]] / total_unigrams

            denominator = p_t1 * p_t2
            if denominator <= 0:
                continue

            pmi = math.log2(p_bg / denominator)
            if pmi >= self.min_pmi:
                firm_cnt = support.firm_count(bg) if support else 1
                sic_cnt = support.sic_count(bg) if support else 1
                scope = support.classify_scope(bg) if support else "FIRM"
                candidates.append(
                    CandidatePhrase(
                        phrase=bg,
                        frequency=freq,
                        pmi=round(pmi, 4),
                        firm_count=firm_cnt,
                        sic_count=sic_cnt,
                        scope=scope,
                    )
                )

        candidates.sort(key=lambda c: (c.pmi, c.frequency), reverse=True)
        return candidates


class ArcPolarityResolver:
    """Extracts algebraic relations and polarities from calculation linkbases."""

    @staticmethod
    def resolve_arcs(
        calculation_arcs: Sequence[CalculationArc],
        support: SupportCounter | None = None,
    ) -> list[CandidateRelation]:
        """Convert calculation arcs into candidate typed relations with support scores."""
        relations: list[CandidateRelation] = []
        for arc in calculation_arcs:
            parent_local = arc.parent_qname.split(":")[-1]
            child_local = arc.child_qname.split(":")[-1]
            key = (child_local, parent_local)

            firm_cnt = support.firm_count(key) if support else 1
            sic_cnt = support.sic_count(key) if support else 1
            scope = support.classify_scope(key) if support else "FIRM"

            rel_type = "PART_OF" if arc.weight >= 0 else "CONTRA_OF"
            formula_id = f"FORMULA_{parent_local.upper()}"

            relations.append(
                CandidateRelation(
                    source_concept=arc.child_qname,
                    target_concept=arc.parent_qname,
                    algebraic_weight=arc.weight,
                    relation_type=rel_type,
                    formula_id=formula_id,
                    firm_count=firm_cnt,
                    sic_count=sic_cnt,
                    scope=scope,
                )
            )

        return relations
