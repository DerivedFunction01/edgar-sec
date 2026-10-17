"""Ergonomic XBRL facts, statement graphs, and algebraic financial facade."""

from __future__ import annotations

from edgar_sec.apps.client.facts import XbrlFactSet
from edgar_sec.apps.client.financials import XbrlFinancials
from edgar_sec.apps.client.statements import XbrlStatements
from edgar_sec.apps.client.views import StatementView
from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.schema.models import FilingXbrl
from edgar_sec.engine.xbrl.solve.query import (
    FinancialQuery,
    FinancialQueryEngine,
    FinancialQueryResult,
    QueryMode,
)
from edgar_sec.engine.xbrl.solve.solver import XbrlConstraintSolver
from edgar_sec.engine.xbrl.solve.statement import (
    StatementGraph,
    StatementNode,
    build_statement_graph,
)
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy, load_domain_taxonomy


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
        labels = self._filing.linkbases.labels if self._filing.linkbases else {}

        self.facts = XbrlFactSet(self._filing.facts, self._taxonomy)
        self.statements = XbrlStatements(
            self._filing.facts, arcs, self._taxonomy, labels
        )
        self.financials = XbrlFinancials(
            self._filing.facts, arcs, self._taxonomy, labels
        )

        kb = EvidenceKnowledgeBase(self._taxonomy)
        solver = XbrlConstraintSolver(kb)
        self._query_engine = FinancialQueryEngine(solver)

    def query(
        self,
        term: str,
        mode: str = "REPORTED_ONLY",
        fiscal_year: int | None = None,
    ) -> FinancialQueryResult:
        """Query reported or solved financial concepts across the filing."""
        query_mode = (
            QueryMode.SOLVED_FALLBACK
            if mode == "SOLVED_FALLBACK"
            else QueryMode.REPORTED_ONLY
        )
        q = FinancialQuery(query_term=term, mode=query_mode, fiscal_year=fiscal_year)
        arcs = self._filing.linkbases.calculation_arcs if self._filing.linkbases else ()
        return self._query_engine.query(
            q, facts=self._filing.facts, calculation_arcs=arcs
        )

    def graph(
        self,
        root_concept: str,
        period_type: str = "duration",
        year: int | str | None = None,
    ) -> StatementView:
        """Construct an algebraic StatementView for any arbitrary concept in the filing."""
        arcs = self._filing.linkbases.calculation_arcs if self._filing.linkbases else ()
        labels = self._filing.linkbases.labels if self._filing.linkbases else {}
        graph = build_statement_graph(
            root_concept=root_concept,
            statement_type=f"Custom: {root_concept}",
            facts=self._filing.facts,
            arcs=arcs,
            taxonomy=self._taxonomy,
            labels=labels,
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

    def __repr__(self) -> str:
        return f"<Xbrl accession={self._filing.accession} facts={len(self.facts)}>"
