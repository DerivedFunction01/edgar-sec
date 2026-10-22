"""Scoped concept queries over filing facts and accounting graphs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping

from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.schema.models import AggregateFact, CalculationArc, XbrlFact
from edgar_sec.engine.xbrl.solve.equivalence import EXACT, RankedEquivalent
from edgar_sec.engine.xbrl.solve.scoping import FactScope
from edgar_sec.engine.xbrl.solve.solver import XbrlConstraintSolver
from edgar_sec.engine.xbrl.solve.tokenizer import ConceptTokenizer
from edgar_sec.engine.xbrl.normalize.decomposer import decompose_concept
from edgar_sec.engine.xbrl.normalize.decomposer import residual_counts
from edgar_sec.engine.xbrl.normalize.decomposer import split_camel_case


class QueryMode(StrEnum):
    REPORTED_ONLY = "REPORTED_ONLY"
    DERIVE_ONLY = "DERIVE_ONLY"
    VERIFY_DERIVATION = "VERIFY_DERIVATION"


class QueryStatus(StrEnum):
    REPORTED = "REPORTED"
    DERIVED = "DERIVED"
    VERIFIED = "VERIFIED"
    AMBIGUOUS = "AMBIGUOUS"
    UNAVAILABLE = "UNAVAILABLE"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True, slots=True)
class FinancialQuery:
    term: str
    scope: FactScope
    mode: QueryMode = QueryMode.REPORTED_ONLY


@dataclass(frozen=True, slots=True)
class FinancialQueryResult:
    query: FinancialQuery
    status: QueryStatus
    candidate_qnames: tuple[str, ...] = ()
    candidate_facts: tuple[XbrlFact, ...] = ()
    target_atom: Atom | None = None
    reported_fact: XbrlFact | None = None
    aggregate: AggregateFact | None = None
    discrepancy: float | None = None
    message: str = ""
    tier: str = ""
    equivalents: tuple[RankedEquivalent, ...] = ()

    @property
    def value(self) -> float | None:
        if self.aggregate is not None:
            return self.aggregate.value
        if self.reported_fact is not None and isinstance(
            self.reported_fact.value, (int, float)
        ):
            return float(self.reported_fact.value)
        return None


DEFAULT_ALIASES: Mapping[str, tuple[str, ...]] = {
    "aoci": (
        "us-gaap:AccumulatedOtherComprehensiveIncomeLossNetOfTax",
        "us-gaap:OtherComprehensiveIncomeLossNetOfTaxPortionAttributableToParent",
    ),
    "cfo": ("us-gaap:NetCashProvidedByUsedInOperatingActivities",),
    "eps": (
        "us-gaap:EarningsPerShareBasic",
        "us-gaap:EarningsPerShareDiluted",
    ),
}


class FinancialQueryEngine:
    def __init__(
        self,
        solver: XbrlConstraintSolver,
        aliases: Mapping[str, tuple[str, ...]] | None = None,
    ) -> None:
        self.solver = solver
        self.taxonomy = solver.kb.taxonomy
        self.aliases = aliases or DEFAULT_ALIASES

    @staticmethod
    def _normalize_term(term: str) -> str:
        return "".join(
            character.casefold() for character in term if character.isalnum()
        )

    @staticmethod
    def _context_key(fact: XbrlFact) -> tuple[object, ...]:
        return (
            str(fact.accession),
            fact.unit,
            fact.period_type,
            fact.start_date,
            fact.end_date,
            fact.instant_date,
            tuple(sorted(fact.dimensions.items())),
        )

    def _resolve_candidates(
        self,
        term: str,
        scoped_facts: tuple[XbrlFact, ...],
        facts: tuple[XbrlFact, ...],
        calculation_arcs: tuple[CalculationArc, ...],
    ) -> tuple[tuple[str, ...], Atom | None, tuple[RankedEquivalent, ...]]:
        qnames = {fact.concept_qname for fact in facts}
        qnames.update(arc.parent_qname for arc in calculation_arcs)
        available = {fact.concept_qname for fact in scoped_facts}
        available.update(arc.parent_qname for arc in calculation_arcs)
        normalized = self._normalize_term(term)
        alias_names = self.aliases.get(normalized)
        if alias_names is not None:
            known = set(alias_names) & qnames
            if not known:
                return (), None, ()
            scoped = known & available
            return tuple(sorted(scoped or known)), None, ()
        if ":" in term:
            return ((term,) if term in qnames else ()), None, ()

        lexicon = self.taxonomy.token_lexicon
        if lexicon is None:
            return (), None, ()
        target_atom, residuals, _, _ = decompose_concept(term, lexicon)
        if target_atom.head == "H_UNKNOWN" or residuals:
            return (), target_atom, ()

        numeric = self._numeric_qnames(scoped_facts)
        decomposed = {
            qname: decompose_concept(qname, lexicon)
            for qname in qnames
            if qname in available and qname in numeric
        }
        atoms = {qname: result[0] for qname, result in decomposed.items()}
        matches = {qname for qname, atom in atoms.items() if atom == target_atom}
        if matches:
            return (
                tuple(
                    sorted(
                        matches,
                        key=lambda qname: (
                            *residual_counts(decomposed[qname][1]),
                            qname,
                        ),
                    )
                ),
                target_atom,
                (),
            )
        ranked = ConceptTokenizer(self.taxonomy).equivalents(
            target_atom, tuple(sorted(atoms.items()))
        )
        if not ranked:
            return (), target_atom, ()
        best = ranked[0]
        if best.tier == EXACT:
            tied = tuple(
                item.qname
                for item in ranked
                if (item.tier, item.via_default, item.modifier_distance)
                == (best.tier, best.via_default, best.modifier_distance)
            )
            return tied, target_atom, ranked
        tier_group = tuple(
            item
            for item in ranked
            if (item.tier, item.via_default) == (best.tier, best.via_default)
        )
        if len(tier_group) == 1 or self._tier_values_agree(
            tier_group, scoped_facts
        ):
            return (best.qname,), target_atom, ranked
        return tuple(item.qname for item in tier_group), target_atom, ranked

    @staticmethod
    def _numeric_qnames(scoped_facts: tuple[XbrlFact, ...]) -> set[str]:
        """Qnames carrying at least one numeric fact in the scoped pool.

        Interim substance guard: text-only concepts cannot satisfy a
        numeric query; the Phase 1 type coordinate replaces this.
        """
        return {
            fact.concept_qname
            for fact in scoped_facts
            if isinstance(fact.value, (int, float))
        }

    @staticmethod
    def _deduplicate_context_facts(
        facts: tuple[XbrlFact, ...],
    ) -> tuple[XbrlFact, ...] | None:
        by_context: dict[tuple[object, ...], list[XbrlFact]] = {}
        for fact in facts:
            if not isinstance(fact.value, (int, float)):
                continue
            by_context.setdefault(FinancialQueryEngine._context_key(fact), []).append(
                fact
            )
        deduplicated: list[XbrlFact] = []
        for group in by_context.values():
            representative = FinancialQueryEngine._collapse_context_group(group)
            if representative is None:
                return None
            deduplicated.append(representative)
        return tuple(deduplicated)

    @staticmethod
    def _collapse_context_group(group: list[XbrlFact]) -> XbrlFact | None:
        """Collapse one context group to its most precise fact.

        Facts cluster when their rounding intervals share a common
        intersection; disjoint clusters are a genuine conflict (None).
        """
        ordered = sorted(enumerate(group), key=lambda item: float(item[1].value))
        clusters: list[list[tuple[int, XbrlFact]]] = []
        low = high = 0.0
        for item in ordered:
            fact = item[1]
            tolerance = FinancialQueryEngine._precision_tolerance(fact)
            lo = float(fact.value) - tolerance
            hi = float(fact.value) + tolerance
            if clusters and lo <= high and hi >= low:
                clusters[-1].append(item)
                low, high = max(low, lo), min(high, hi)
            else:
                clusters.append([item])
                low, high = lo, hi
        if len(clusters) > 1:
            return None
        return min(
            clusters[0],
            key=lambda item: (
                FinancialQueryEngine._precision_tolerance(item[1]),
                item[0],
            ),
        )[1]

    @staticmethod
    def _precision_tolerance(fact: XbrlFact) -> float:
        if fact.decimals is None:
            return 0.0001
        return 0.5 * (10.0 ** (-fact.decimals))

    def _tier_values_agree(
        self,
        group: tuple[RankedEquivalent, ...],
        scoped_facts: tuple[XbrlFact, ...],
    ) -> bool:
        """True when each candidate has one in-scope value and all agree.

        Agreement is a common intersection of precision intervals.
        """
        low: float | None = None
        high: float | None = None
        for item in group:
            facts = tuple(
                fact for fact in scoped_facts if fact.concept_qname == item.qname
            )
            deduped = self._deduplicate_context_facts(facts)
            if deduped is None or len(deduped) != 1:
                return False
            fact = deduped[0]
            tolerance = self._precision_tolerance(fact)
            lo = float(fact.value) - tolerance
            hi = float(fact.value) + tolerance
            low = lo if low is None else max(low, lo)
            high = hi if high is None else min(high, hi)
            if low > high:
                return False
        return True

    def _derivation_is_scope_faithful(
        self,
        query: FinancialQuery,
        target: str,
        facts: tuple[XbrlFact, ...],
        reported_fact: XbrlFact | None,
    ) -> bool:
        """Check a derivation scope against the target concept's own facts.

        The scope's period kind must be among the target's period
        types, and its unit must share the target's unit class.
        """
        target_facts = [fact for fact in facts if fact.concept_qname == target]
        scope_kind = "instant" if query.scope.instant_date else "duration"
        period_types = {fact.period_type for fact in target_facts}
        if period_types and scope_kind not in period_types:
            return False
        scope_unit = query.scope.unit or (
            reported_fact.unit if reported_fact is not None else None
        )
        if scope_unit is None:
            return True
        target_classes = {
            self.taxonomy.normalize_unit(fact.unit)
            for fact in target_facts
            if fact.unit is not None
        }
        return (
            not target_classes
            or self.taxonomy.normalize_unit(scope_unit) in target_classes
        )

    def execute(
        self,
        query: FinancialQuery,
        facts: tuple[XbrlFact, ...] | list[XbrlFact],
        calculation_arcs: tuple[CalculationArc, ...] | list[CalculationArc] = (),
    ) -> FinancialQueryResult:
        all_facts = tuple(facts)
        arcs = tuple(calculation_arcs)
        scoped_facts = query.scope.select(list(all_facts))
        accessions = {str(fact.accession) for fact in scoped_facts}
        if query.scope.accession is None and len(accessions) > 1:
            return FinancialQueryResult(
                query,
                QueryStatus.AMBIGUOUS,
                candidate_facts=scoped_facts,
                message="A filing accession is required to prevent cross-entity matches.",
            )
        candidates, atom, ranked = self._resolve_candidates(
            query.term, scoped_facts, all_facts, arcs
        )
        tier = ranked[0].tier if ranked else ""
        if not candidates:
            return FinancialQueryResult(
                query,
                QueryStatus.UNAVAILABLE,
                target_atom=atom,
                message="No concept in this filing matches the query term.",
            )
        if len(candidates) > 1:
            return FinancialQueryResult(
                query,
                QueryStatus.AMBIGUOUS,
                candidate_qnames=candidates,
                target_atom=atom,
                message="The query term resolves to multiple concepts.",
                tier=tier,
                equivalents=ranked,
            )

        target = candidates[0]
        target_facts = tuple(
            fact for fact in scoped_facts if fact.concept_qname == target
        )
        numeric_targets = self._deduplicate_context_facts(target_facts)
        if numeric_targets is None:
            return FinancialQueryResult(
                query,
                QueryStatus.CONFLICT,
                candidate_qnames=candidates,
                candidate_facts=target_facts,
                target_atom=atom,
                message="Conflicting values exist in the selected XBRL context.",
                tier=tier,
                equivalents=ranked,
            )
        if len(numeric_targets) > 1:
            return FinancialQueryResult(
                query,
                QueryStatus.AMBIGUOUS,
                candidate_qnames=candidates,
                candidate_facts=numeric_targets,
                target_atom=atom,
                message="The query scope matches multiple fact contexts.",
                tier=tier,
                equivalents=ranked,
            )
        reported_fact = numeric_targets[0] if numeric_targets else None

        if reported_fact is None and query.mode == QueryMode.REPORTED_ONLY:
            return FinancialQueryResult(
                query,
                QueryStatus.UNAVAILABLE,
                candidate_qnames=candidates,
                target_atom=atom,
                message="No reported fact exists in the selected XBRL context.",
                tier=tier,
                equivalents=ranked,
            )
        if reported_fact is not None and query.mode == QueryMode.REPORTED_ONLY:
            return FinancialQueryResult(
                query,
                QueryStatus.REPORTED,
                candidate_qnames=candidates,
                target_atom=atom,
                reported_fact=reported_fact,
                tier=tier,
                equivalents=ranked,
            )

        if query.scope.instant_date is None and query.scope.start_date is None:
            return FinancialQueryResult(
                query,
                QueryStatus.AMBIGUOUS,
                candidate_qnames=candidates,
                candidate_facts=target_facts,
                target_atom=atom,
                reported_fact=reported_fact,
                message="A query period is required to derive across filing facts.",
                tier=tier,
                equivalents=ranked,
            )

        if query.scope.unit is None:
            units = {fact.unit for fact in scoped_facts if fact.unit is not None}
            if len(units) > 1:
                return FinancialQueryResult(
                    query,
                    QueryStatus.AMBIGUOUS,
                    candidate_qnames=candidates,
                    candidate_facts=target_facts,
                    target_atom=atom,
                    reported_fact=reported_fact,
                    message="A query unit is required to prevent mixed-unit derivation.",
                    tier=tier,
                    equivalents=ranked,
                )

        derivation_atom = atom
        if derivation_atom is None and self.taxonomy.token_lexicon is not None:
            derivation_atom = decompose_concept(target, self.taxonomy.token_lexicon)[0]
        derive_facts = tuple(
            fact
            for fact in scoped_facts
            if fact.concept_qname != target
            and not (
                derivation_atom is not None
                and self.taxonomy.token_lexicon is not None
                and decompose_concept(fact.concept_qname, self.taxonomy.token_lexicon)[
                    0
                ]
                == derivation_atom
            )
        )
        period = query.scope.instant_date or query.scope.end_date or ""
        unit = query.scope.unit or (reported_fact.unit if reported_fact else "USD")
        faithful = self._derivation_is_scope_faithful(
            query, target, all_facts, reported_fact
        )
        aggregate = (
            self.solver.evaluate_goal(
                target,
                derive_facts,
                arcs,
                entity=query.scope.accession or "",
                period=period,
                unit=unit,
            )
            if faithful
            else None
        )
        if aggregate is None or aggregate.value is None:
            if query.mode == QueryMode.VERIFY_DERIVATION and reported_fact is not None:
                return FinancialQueryResult(
                    query,
                    QueryStatus.REPORTED,
                    candidate_qnames=candidates,
                    target_atom=atom,
                    reported_fact=reported_fact,
                    message="The reported fact exists but no graph derivation was available.",
                    tier=tier,
                    equivalents=ranked,
                )
            return FinancialQueryResult(
                query,
                QueryStatus.UNAVAILABLE,
                candidate_qnames=candidates,
                target_atom=atom,
                reported_fact=reported_fact,
                aggregate=aggregate,
                message="No derivation is available from the selected context.",
                tier=tier,
                equivalents=ranked,
            )

        if query.mode == QueryMode.VERIFY_DERIVATION and reported_fact is not None:
            discrepancy = abs(float(reported_fact.value) - aggregate.value)
            tolerance = self._precision_tolerance(reported_fact)
            status = (
                QueryStatus.VERIFIED
                if discrepancy <= tolerance
                else QueryStatus.CONFLICT
            )
            return FinancialQueryResult(
                query,
                status,
                candidate_qnames=candidates,
                target_atom=atom,
                reported_fact=reported_fact,
                aggregate=aggregate,
                discrepancy=discrepancy,
                message=(
                    "Graph derivation reconciles to the reported fact."
                    if status == QueryStatus.VERIFIED
                    else "Graph derivation does not reconcile to the reported fact."
                ),
                tier=tier,
                equivalents=ranked,
            )

        return FinancialQueryResult(
            query,
            QueryStatus.DERIVED,
            candidate_qnames=candidates,
            target_atom=atom,
            reported_fact=reported_fact,
            aggregate=aggregate,
            tier=tier,
            equivalents=ranked,
        )

    def parse_terms(self, term: str) -> tuple[str, ...]:
        return split_camel_case(term)
