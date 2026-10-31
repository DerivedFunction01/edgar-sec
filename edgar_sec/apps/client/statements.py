"""Statement views as coordinate presets over the shared filing kernel.

Discovery is the engine composer's, fed by the kernel's record-first
atom source; this surface wraps its graphs in client views.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from edgar_sec.apps.client.catalog import (
    CatalogEntry,
    build_catalog,
    catalog_by_category,
    catalog_frame,
    catalog_get,
    catalog_search,
)
from edgar_sec.apps.client.display import filing_header
from edgar_sec.apps.client.kernel import FilingKernel
from edgar_sec.apps.client.presentation import (
    PresentationView,
    build_presentation_view,
)
from edgar_sec.apps.client.rollforwards import build_fair_value_hierarchy
from edgar_sec.apps.client.topics import (
    build_cash_rollforward,
    build_debt_structure,
    build_derivative_portfolio,
)
from edgar_sec.apps.client.views import (
    CashRollforwardView,
    DebtStructureView,
    DerivativePortfolioView,
    EquityRollforwardView,
    FairValueHierarchyView,
    StatementView,
)
from edgar_sec.engine.xbrl.schema.models import XbrlFact, split_concept_qname
from edgar_sec.engine.xbrl.solve.statement import (
    StatementGraph,
    build_statement_graph,
)

if TYPE_CHECKING:
    import pandas as pd


class XbrlStatements:
    """Statement factory for operations, balance sheet, cash flows, and equity."""

    def __init__(self, kernel: FilingKernel) -> None:
        self._kernel = kernel
        self._catalog_entries: tuple[CatalogEntry, ...] | None = None

    def _catalog(self) -> tuple[CatalogEntry, ...]:
        if self._catalog_entries is None:
            self._catalog_entries = build_catalog(self._kernel)
        return self._catalog_entries

    def _header(self) -> str | None:
        """Filing identity header for rendered statements, when known."""
        kernel = self._kernel
        return filing_header(kernel.registrant_name, kernel.cik, kernel.accession)

    def list_available(self) -> pd.DataFrame:
        """Catalog of this filing's presentation roles as a DataFrame."""
        return catalog_frame(self._catalog())

    def get(self, role_or_title: str) -> CatalogEntry | None:
        """Resolve one catalog entry by role URI or title."""
        return catalog_get(self._catalog(), role_or_title)

    def search(self, term: str) -> tuple[CatalogEntry, ...]:
        """Catalog entries whose title carries every token of the term."""
        return catalog_search(self._catalog(), term)

    def by_category(self, category: str) -> tuple[CatalogEntry, ...]:
        """Catalog entries in one category, in catalog order."""
        return catalog_by_category(self._catalog(), category)

    def view(self, role_or_title: str, *, mode: str = "standard") -> PresentationView:
        """Build one catalog role's presentation view in a dimensional mode."""
        entry = catalog_get(self._catalog(), role_or_title)
        if entry is None:
            raise ValueError(f"no presentation role matches {role_or_title!r}")
        return build_presentation_view(self._kernel, entry, mode)

    def income_statement(
        self,
        period: str | None = None,
        year: int | str | None = None,
    ) -> StatementView:
        """Construct the algebraic Statement of Operations rollup view."""
        graph = self._kernel.compose_income_statement(period, year)
        return StatementView(graph, header=self._header())

    def balance_sheet(
        self,
        period: str | None = None,
        year: int | str | None = None,
    ) -> StatementView:
        """Construct the algebraic Balance Sheet rollup view."""
        graph = self._kernel.compose_balance_sheet(period, year)
        return StatementView(graph, header=self._header())

    def cash_flow_statement(
        self,
        period: str | None = None,
        year: int | str | None = None,
    ) -> StatementView:
        """Construct the algebraic Statement of Cash Flows rollup view."""
        graph = self._kernel.compose_cash_flow(period, year)
        return StatementView(graph, header=self._header())

    def equity_rollforward(
        self,
        member_qname: str | None = None,
        year: int | str | None = None,
    ) -> EquityRollforwardView:
        """Construct the statement of changes in equity, verified by identity."""
        return self._kernel.equity_rollforward(member_qname=member_qname, year=year)

    def comprehensive_income_statement(
        self,
        period: str | None = None,
        year: int | str | None = None,
    ) -> StatementView:
        """Construct the Statement of Comprehensive Income rollup view."""
        graph = self._kernel.graph_once(
            ("comprehensive_income", period, year),
            lambda: self._build_comprehensive(period, year),
        )
        return StatementView(graph, header=self._header())

    def _build_comprehensive(
        self, period: str | None, year: int | str | None
    ) -> StatementGraph:
        composer = self._kernel.composer
        root = (
            composer.find_concept_by_atom("H_INCOME", frozenset({"M_COMPREHENSIVE"}))
            or composer.find_concept_by_atom("H_INCOME", frozenset({"M_OCI"}))
            or ""
        )
        return build_statement_graph(
            root_concept=root,
            statement_type="Comprehensive Income",
            facts=self._kernel.facts,
            arcs=self._kernel.calculation_arcs,
            taxonomy=self._kernel.taxonomy,
            labels=self._kernel.labels,
            period_type="duration",
            end_date=period,
            year=year,
            graph_cls=StatementGraph,
        )

    def cover(self) -> tuple[XbrlFact, ...]:
        """Return the filing's dei cover facts, sorted by concept."""
        return tuple(
            sorted(
                (
                    fact
                    for fact in self._kernel.facts
                    if split_concept_qname(fact.concept_qname)[0] == "dei"
                ),
                key=lambda fact: (
                    fact.concept_qname,
                    fact.instant_date or fact.end_date or fact.start_date or "",
                ),
            )
        )

    def derivatives(self) -> DerivativePortfolioView:
        """Resolve derivative exposures, risk categories, and netting."""
        graph = self._kernel.graph_once(
            ("derivatives",),
            lambda: build_derivative_portfolio(
                self._kernel.facts,
                self._kernel.records,
                self._kernel.taxonomy,
                self._kernel.labels,
            ),
        )
        return DerivativePortfolioView(graph)

    def debt(self) -> DebtStructureView:
        """Resolve capital structure, debt tranches, and maturities."""
        graph = self._kernel.graph_once(
            ("debt",),
            lambda: build_debt_structure(
                self._kernel.facts,
                self._kernel.records,
                self._kernel.taxonomy,
                self._kernel.labels,
            ),
        )
        return DebtStructureView(graph)

    def cash_rollforward(self) -> CashRollforwardView:
        """Resolve the ASU 2016-18 cash and restricted-cash rollforward."""
        graph = self._kernel.graph_once(
            ("cash_rollforward",),
            lambda: build_cash_rollforward(
                self._kernel.facts,
                self._kernel.records,
                self._kernel.taxonomy,
                self._kernel.labels,
                calculation_arcs=self._kernel.calculation_arcs,
            ),
        )
        return CashRollforwardView(graph)

    def fair_value_hierarchy(
        self,
        year: int | str | None = None,
    ) -> FairValueHierarchyView:
        """Resolve each concept's fair-value level split against its total."""
        graph = self._kernel.graph_once(
            ("fair_value_hierarchy", year),
            lambda: build_fair_value_hierarchy(
                self._kernel.facts,
                self._kernel.records,
                self._kernel.taxonomy,
                self._kernel.labels,
                year,
            ),
        )
        return FairValueHierarchyView(graph)
