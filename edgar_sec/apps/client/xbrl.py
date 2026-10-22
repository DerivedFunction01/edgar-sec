"""Ergonomic XBRL facts, statement graphs, and algebraic financial facade."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from edgar_sec.apps.client.comparison import ComparisonView, compare_companies
from edgar_sec.apps.client.facts import XbrlFactSet
from edgar_sec.apps.client.financials import XbrlFinancials
from edgar_sec.apps.client.statements import XbrlStatements
from edgar_sec.apps.client.views import StatementView
from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.schema.models import (
    CalculationArc,
    ConceptDeclaration,
    ConceptLabel,
    FilingXbrl,
    LinkbaseBundle,
)
from edgar_sec.engine.xbrl.solve.query import (
    FinancialQuery,
    FinancialQueryEngine,
    FinancialQueryResult,
    QueryMode,
    QueryStatus,
)
from edgar_sec.engine.xbrl.solve.scoping import FactScope
from edgar_sec.engine.xbrl.solve.solver import XbrlConstraintSolver
from edgar_sec.engine.xbrl.solve.statement import (
    StatementGraph,
    StatementNode,
    build_statement_graph,
)
from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy, load_domain_taxonomy
from edgar_sec.engine.xbrl.taxonomy.item_types import (
    declaration_for,
    load_standard_item_types,
)

_STANDARD_LABEL_ROLE = "http://www.xbrl.org/2003/role/label"
_SUCCESS_STATUSES = frozenset(
    {QueryStatus.REPORTED, QueryStatus.DERIVED, QueryStatus.VERIFIED}
)
_PRECEDENCE_RANK = {
    QueryStatus.VERIFIED: 0,
    QueryStatus.REPORTED: 1,
    QueryStatus.CONFLICT: 2,
    QueryStatus.DERIVED: 3,
    QueryStatus.AMBIGUOUS: 4,
    QueryStatus.UNAVAILABLE: 5,
}


def _labels_by_concept(labels: Sequence[ConceptLabel]) -> dict[str, str]:
    best: dict[str, tuple[tuple[int, int], str]] = {}
    for label in labels:
        rank = (
            0 if label.role_uri == _STANDARD_LABEL_ROLE else 1,
            0 if label.lang == "en-US" else 1,
        )
        current = best.get(label.concept_qname)
        if current is None or rank < current[0]:
            best[label.concept_qname] = (rank, label.label)
    return {qname: text for qname, (_, text) in best.items()}


def _duration_span_key(period: tuple[str, str]) -> tuple[int, str, str]:
    start, end = period
    try:
        span = (date.fromisoformat(end) - date.fromisoformat(start)).days
    except ValueError:
        span = -1
    return (-span, start, end)


class Xbrl:
    """Unified Layer 5 XBRL client facade providing algebraic graphs and fact queries."""

    def __init__(
        self,
        filing_xbrl: FilingXbrl,
        taxonomy: DomainTaxonomy | None = None,
    ) -> None:
        self._filing = filing_xbrl
        self._taxonomy = taxonomy or load_domain_taxonomy()

        arcs = self._filing.linkbases.calculation_arcs if self._filing.linkbases else ()
        raw_labels = self._filing.linkbases.labels if self._filing.linkbases else ()
        self._labels = _labels_by_concept(raw_labels)

        declarations = self._merged_declarations(arcs)
        self.facts = XbrlFactSet(
            self._filing.facts, self._taxonomy, declarations=declarations
        )
        self.statements = XbrlStatements(
            self._filing.facts, arcs, self._taxonomy, self._labels
        )
        self.financials = XbrlFinancials(
            self._filing.facts,
            arcs,
            self._taxonomy,
            self._labels,
            display_records=self.facts.records,
        )

        kb = EvidenceKnowledgeBase(self._taxonomy)
        solver = XbrlConstraintSolver(kb)
        self._query_engine = FinancialQueryEngine(solver, declarations=declarations)

    def _merged_declarations(
        self, arcs: tuple[CalculationArc, ...]
    ) -> dict[str, ConceptDeclaration]:
        """Bundle declarations merged over the standard item-type table."""
        extension = {}
        if self._filing.linkbases is not None:
            extension = {
                item.concept_qname: item for item in self._filing.linkbases.declarations
            }
        table = load_standard_item_types(
            resolve_xbrl_paths().default_standard_item_types_path
        )
        qnames = {fact.concept_qname for fact in self._filing.facts}
        for arc in arcs:
            qnames.update((arc.parent_qname, arc.child_qname))
        merged = {}
        for qname in sorted(qnames):
            declaration = declaration_for(qname, table, extension)
            if declaration is not None:
                merged[qname] = declaration
        return merged

    @property
    def accession(self) -> str:
        """Return the filing accession number."""
        return str(self._filing.accession)

    @property
    def cik(self) -> str:
        """Return the filer CIK."""
        return str(self._filing.cik)

    @property
    def linkbases(self) -> LinkbaseBundle | None:
        """Return raw linkbase bundle attached to this filing."""
        return self._filing.linkbases

    def query(
        self,
        term: str,
        mode: QueryMode | str = QueryMode.REPORTED_ONLY,
        fiscal_year: int | None = None,
        scope: FactScope | None = None,
    ) -> FinancialQueryResult:
        """Query a concept, synthesizing an exact scope from fiscal_year if needed.

        An explicit scope is executed verbatim; unknown mode strings raise ValueError.
        """
        query_mode = self._parse_query_mode(mode)
        arcs = self._filing.linkbases.calculation_arcs if self._filing.linkbases else ()
        if scope is not None:
            return self._execute_query(term, query_mode, scope, arcs)
        accession = self._scope_accession()
        if fiscal_year is None:
            return self._execute_query(
                term, query_mode, FactScope(accession=accession), arcs
            )
        candidates = self._candidate_scopes(accession, fiscal_year)
        if not candidates:
            return self._execute_query(
                term, query_mode, FactScope(accession=accession), arcs
            )
        return self._execute_fiscal_year_query(
            term, query_mode, fiscal_year, candidates, arcs
        )

    @staticmethod
    def _parse_query_mode(mode: QueryMode | str) -> QueryMode:
        if isinstance(mode, QueryMode):
            return mode
        try:
            return QueryMode(mode)
        except ValueError:
            raise ValueError(f"Unknown XBRL query mode: {mode!r}") from None

    def _execute_query(
        self,
        term: str,
        mode: QueryMode,
        scope: FactScope,
        arcs: Sequence[CalculationArc],
    ) -> FinancialQueryResult:
        query = FinancialQuery(term=term, scope=scope, mode=mode)
        return self._query_engine.execute(
            query, facts=self._filing.facts, calculation_arcs=arcs
        )

    def _scope_accession(self) -> str:
        accessions = {str(fact.accession) for fact in self._filing.facts}
        if len(accessions) == 1:
            return accessions.pop()
        return str(self._filing.accession)

    def _candidate_scopes(
        self, accession: str, fiscal_year: int
    ) -> tuple[FactScope, ...]:
        year = str(fiscal_year)
        durations: set[tuple[str, str]] = set()
        instants: set[str] = set()
        for fact in self._filing.facts:
            if fact.dimensions:
                continue
            if (
                fact.period_type == "duration"
                and fact.start_date
                and fact.end_date
                and fact.end_date[:4] == year
            ):
                durations.add((fact.start_date, fact.end_date))
            elif (
                fact.period_type == "instant"
                and fact.instant_date
                and fact.instant_date[:4] == year
            ):
                instants.add(fact.instant_date)
        periods: list[tuple[str | None, str | None, str | None]] = [
            (start, end, None)
            for start, end in sorted(durations, key=_duration_span_key)
        ]
        periods.extend((None, None, instant) for instant in sorted(instants))
        scopes: list[FactScope] = []
        for start, end, instant in periods:
            scopes.append(
                FactScope(
                    accession=accession,
                    start_date=start,
                    end_date=end,
                    instant_date=instant,
                )
            )
            for unit in self._period_units(start, end, instant):
                scopes.append(
                    FactScope(
                        accession=accession,
                        start_date=start,
                        end_date=end,
                        instant_date=instant,
                        unit=unit,
                    )
                )
        return tuple(scopes)

    def _execute_fiscal_year_query(
        self,
        term: str,
        mode: QueryMode,
        fiscal_year: int,
        candidates: tuple[FactScope, ...],
        arcs: Sequence[CalculationArc],
    ) -> FinancialQueryResult:
        """Answer from the faithful tiers: longest-span durations, then FYE instants.

        Non-annual scopes never answer a fiscal-year query; if both tiers are
        silent, the first candidate scope's result (UNAVAILABLE) stands.
        """
        duration_tier, instant_tier = self._fiscal_year_tiers(fiscal_year, candidates)
        outcome, first, results = self._tier_outcome(term, mode, duration_tier, arcs)
        if outcome is not None and outcome.status in _SUCCESS_STATUSES:
            return outcome
        if (
            outcome is not None
            and outcome.status != QueryStatus.UNAVAILABLE
            and self._tier_is_duration_opinion(results)
        ):
            return outcome
        instant_outcome, _, _ = self._tier_outcome(term, mode, instant_tier, arcs)
        if outcome is not None and outcome.status != QueryStatus.UNAVAILABLE:
            return instant_outcome if instant_outcome is not None else outcome
        if (
            instant_outcome is not None
            and instant_outcome.status != QueryStatus.UNAVAILABLE
        ):
            return instant_outcome
        if first is not None:
            return first
        return self._execute_query(term, mode, candidates[0], arcs)

    def _tier_outcome(
        self,
        term: str,
        mode: QueryMode,
        scopes: tuple[FactScope, ...],
        arcs: Sequence[CalculationArc],
    ) -> tuple[
        FinancialQueryResult | None,
        FinancialQueryResult | None,
        tuple[FinancialQueryResult, ...],
    ]:
        """Best outcome in the tier under the split precedence; ties keep scope order.

        VERIFIED > REPORTED > CONFLICT > DERIVED > AMBIGUOUS > UNAVAILABLE.
        """
        first: FinancialQueryResult | None = None
        outcome: FinancialQueryResult | None = None
        results: list[FinancialQueryResult] = []
        for scope in scopes:
            result = self._execute_query(term, mode, scope, arcs)
            if first is None:
                first = result
            results.append(result)
            if outcome is None or (
                _PRECEDENCE_RANK[result.status] < _PRECEDENCE_RANK[outcome.status]
            ):
                outcome = result
        return outcome, first, tuple(results)

    def _tier_is_duration_opinion(
        self, results: tuple[FinancialQueryResult, ...]
    ) -> bool:
        """Whether any candidate on the tier's results carries a duration fact here."""
        qnames = {qname for result in results for qname in result.candidate_qnames}
        return any(
            fact.concept_qname in qnames and fact.period_type == "duration"
            for fact in self._filing.facts
        )

    def _fiscal_year_tiers(
        self, fiscal_year: int, candidates: tuple[FactScope, ...]
    ) -> tuple[tuple[FactScope, ...], tuple[FactScope, ...]]:
        """Split candidates into the longest-span duration group and the FYE instant group."""
        groups: dict[tuple[str | None, str | None, str | None], list[FactScope]] = {}
        for scope in candidates:
            key = (scope.start_date, scope.end_date, scope.instant_date)
            groups.setdefault(key, []).append(scope)
        spans: dict[tuple[str | None, str | None, str | None], int] = {}
        for key in groups:
            start, end, instant = key
            if instant is None and start is not None and end is not None:
                spans[key] = -_duration_span_key((start, end))[0]
        max_span = max(spans.values(), default=None)
        modal = self._modal_instant(fiscal_year)
        duration_tier = tuple(
            scope
            for key, group in groups.items()
            if spans.get(key) is not None and spans.get(key) == max_span
            for scope in group
        )
        instant_tier = tuple(
            scope
            for key, group in groups.items()
            if key[2] is not None and key[2] == modal
            for scope in group
        )
        return duration_tier, instant_tier

    def _modal_instant(self, fiscal_year: int) -> str | None:
        """Instant carrying the most undimensioned instant facts ending in fiscal_year."""
        counts: dict[str, int] = {}
        year = str(fiscal_year)
        for fact in self._filing.facts:
            if (
                not fact.dimensions
                and fact.period_type == "instant"
                and fact.instant_date
                and fact.instant_date[:4] == year
            ):
                counts[fact.instant_date] = counts.get(fact.instant_date, 0) + 1
        if not counts:
            return None
        return max(counts.items(), key=lambda item: (item[1], item[0]))[0]

    def _period_units(
        self, start: str | None, end: str | None, instant: str | None
    ) -> tuple[str, ...]:
        counts: dict[str, int] = {}
        for fact in self._filing.facts:
            if fact.dimensions or fact.unit is None:
                continue
            if instant is not None:
                matches = fact.period_type == "instant" and fact.instant_date == instant
            else:
                matches = (
                    fact.period_type == "duration"
                    and fact.start_date == start
                    and fact.end_date == end
                )
            if matches:
                counts[fact.unit] = counts.get(fact.unit, 0) + 1
        return tuple(sorted(counts, key=lambda unit: (-counts[unit], unit)))

    def graph(
        self,
        root_concept: str,
        period_type: str = "duration",
        year: int | str | None = None,
    ) -> StatementView:
        """Construct an algebraic StatementView for any arbitrary concept in the filing."""
        arcs = self._filing.linkbases.calculation_arcs if self._filing.linkbases else ()
        graph = build_statement_graph(
            root_concept=root_concept,
            statement_type=f"Custom: {root_concept}",
            facts=self._filing.facts,
            arcs=arcs,
            taxonomy=self._taxonomy,
            labels=self._labels,
            period_type=period_type,
            year=year,
            graph_cls=StatementGraph,
        )
        return StatementView(graph)

    def chain(
        self,
        child_concept: str,
        root_concept: str,
        period_type: str = "duration",
        year: int | str | None = None,
    ) -> tuple[StatementNode, ...]:
        """Trace the upward topological rollup chain from child concept to root."""
        stmt = self.graph(root_concept, period_type=period_type, year=year)
        return stmt.chain(child_concept)

    def compare(
        self,
        others: Sequence[Xbrl],
        metrics: Sequence[str] | None = None,
        year: int | str | None = None,
    ) -> ComparisonView:
        """Compare this filing against other filings across coordinate subspaces."""
        return compare_companies([self, *others], metrics=metrics, year=year)

    def __repr__(self) -> str:
        return f"<Xbrl accession={self._filing.accession} facts={len(self.facts)}>"
