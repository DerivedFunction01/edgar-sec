"""Statement views as coordinate presets over the shared filing kernel.

Discovery is the engine composer's, fed by the kernel's record-first
atom source; this surface wraps its graphs in client views.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from edgar_sec.apps.client.catalog import (
    STATEMENT,
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
from edgar_sec.engine.xbrl.schema.models import (
    XbrlFact,
    qname_local,
    split_concept_qname,
)
from edgar_sec.engine.xbrl.solve.antichain import AntiChainValidator
from edgar_sec.engine.xbrl.solve.statement import (
    StatementGraph,
    build_statement_graph,
)

#: The declared dei axis whose sole member scopes a plan's statement face.
_PLAN_ENTITY_AXIS = "dei:LegalEntityAxis"

if TYPE_CHECKING:
    import pandas as pd


class XbrlStatements:
    """Statement factory for operations, balance sheet, cash flows, and equity."""

    def __init__(self, kernel: FilingKernel) -> None:
        self._kernel = kernel
        self._catalog_entries: tuple[CatalogEntry, ...] | None = None
        self._plan_root_cache: tuple[str, str] | None = None

    def _catalog(self) -> tuple[CatalogEntry, ...]:
        if self._catalog_entries is None:
            self._catalog_entries = build_catalog(self._kernel)
        return self._catalog_entries

    def _header(self) -> str | None:
        """Filing identity header for rendered statements, when known."""
        kernel = self._kernel
        return filing_header(kernel.registrant_name, kernel.cik, kernel.accession)

    def _wrap(self, graph: StatementGraph) -> StatementView:
        """Wrap a composed graph, replacing an absent statement's shell.

        Absence requires both signals: the catalog holds no statement
        roles and composition found no root concept to serve.
        """
        if graph.root_qname == "" and not catalog_by_category(
            self._catalog(), STATEMENT
        ):
            graph = StatementGraph(
                statement_type=graph.statement_type,
                root_qname="",
                nodes={},
                edges=(),
            )
        return StatementView(graph, header=self._header())

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
        return self._wrap(self._kernel.compose_income_statement(period, year))

    def balance_sheet(
        self,
        period: str | None = None,
        year: int | str | None = None,
    ) -> StatementView:
        """Construct the algebraic Balance Sheet rollup view."""
        return self._wrap(self._kernel.compose_balance_sheet(period, year))

    def cash_flow_statement(
        self,
        period: str | None = None,
        year: int | str | None = None,
    ) -> StatementView:
        """Construct the algebraic Statement of Cash Flows rollup view."""
        return self._wrap(self._kernel.compose_cash_flow(period, year))

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
        return self._wrap(graph)

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

    def plan_net_assets(
        self,
        member_qname: str | None = None,
        period: str | None = None,
        year: int | str | None = None,
    ) -> StatementView:
        """Construct the Statement of Net Assets Available for Benefits view."""
        graph = self._kernel.graph_once(
            ("plan_net_assets", member_qname, period, year),
            lambda: self._build_plan(False, member_qname, period, year),
        )
        return self._wrap(graph)

    def plan_changes(
        self,
        member_qname: str | None = None,
        period: str | None = None,
        year: int | str | None = None,
    ) -> StatementView:
        """Construct the Statement of Changes in Net Assets Available for Benefits."""
        graph = self._kernel.graph_once(
            ("plan_changes", member_qname, period, year),
            lambda: self._build_plan(True, member_qname, period, year),
        )
        return self._wrap(graph)

    def _build_plan(
        self,
        changes: bool,
        member_qname: str | None,
        period: str | None,
        year: int | str | None,
    ) -> StatementGraph:
        """Compose one plan statement inside its legal-entity member context."""
        net_root, changes_root = self._plan_roots()
        root = changes_root if changes else net_root
        period_type = "duration" if changes else "instant"
        member = self._plan_member(member_qname, root, period_type) if root else None
        return build_statement_graph(
            root_concept=root if member is not None else "",
            statement_type=(
                "Changes in Net Assets Available for Benefits"
                if changes
                else "Net Assets Available for Benefits"
            ),
            facts=(
                self._plan_scoped_facts(member)
                if member is not None
                else self._kernel.facts
            ),
            arcs=self._kernel.calculation_arcs,
            taxonomy=self._kernel.taxonomy,
            labels=self._kernel.labels,
            period_type=period_type,
            instant_date=None if changes else period,
            end_date=period if changes else None,
            year=year,
            graph_cls=StatementGraph,
        )

    def _plan_roots(self) -> tuple[str, str]:
        """The plan statement root pair, discovered once per filing.

        Plan statements are a regulated pair: unless both roots are
        discovered, neither is served.
        """
        if self._plan_root_cache is None:
            net = self._discover_plan_root({"V_NET"}, {"M_CHANGE"})
            changes = self._discover_plan_root({"M_CHANGE", "V_NET"}, set())
            self._plan_root_cache = (net, changes) if net and changes else ("", "")
        return self._plan_root_cache

    def _discover_plan_root(self, required: set[str], excluded: set[str]) -> str:
        """Winning root: role-rooted, wrapper-free, minimal coordinate.

        A wrapper whose subtree holds another root candidate at the
        identical coordinate is a reconciliation of the root, not it.
        """
        kernel = self._kernel
        arcs = kernel.calculation_arcs
        role_parents: dict[str | None, set[str]] = {}
        role_children: dict[str | None, set[str]] = {}
        for arc in arcs:
            role_parents.setdefault(arc.role_uri, set()).add(arc.parent_qname)
            role_children.setdefault(arc.role_uri, set()).add(arc.child_qname)
        role_roots: set[str] = set()
        for role, parents in role_parents.items():
            role_roots |= parents - role_children.get(role, set())
        parents = {arc.parent_qname for arc in arcs}
        children = {arc.child_qname for arc in arcs}
        ranked: list[tuple[int, int, int, str]] = []
        atoms: dict[str, frozenset[str]] = {}
        for concept in parents | children:
            atom = kernel.atom(concept)
            if atom is None or atom.head != "H_ASSET":
                continue
            mods = set(atom.modifiers)
            if not required <= mods or excluded & mods:
                continue
            if concept not in role_roots:
                continue
            atoms[concept] = frozenset(mods)
            ranked.append(
                (
                    len(mods - required),
                    1 if concept not in parents else 0,
                    len(qname_local(concept)),
                    concept,
                )
            )
        if not ranked:
            return ""
        reach = AntiChainValidator.build_reachability_map(
            [(arc.parent_qname, arc.child_qname, arc.weight) for arc in arcs]
        )
        roots = set(atoms)
        survivors = [
            entry
            for entry in ranked
            if not any(
                atoms[other] == atoms[entry[3]]
                for other in reach.get(entry[3], set()) & roots
                if other != entry[3]
            )
        ]
        pool = survivors or ranked
        pool.sort()
        return pool[0][3]

    def _plan_member(
        self, member_qname: str | None, root: str, period_type: str
    ) -> str | None:
        """The plan entity member carrying the root's filed values.

        The default is the qualifying member whose latest root value
        is largest; an explicit member carrying no root value refuses.
        """
        kernel = self._kernel
        if member_qname is not None:
            members = (member_qname,)
        else:
            members = tuple(
                sorted(
                    {
                        fact.dimensions[_PLAN_ENTITY_AXIS]
                        for fact in kernel.facts
                        if set(fact.dimensions) == {_PLAN_ENTITY_AXIS}
                    }
                )
            )
        best: tuple[float, str] | None = None
        for member in members:
            latest: tuple[str, float] | None = None
            for fact in kernel.facts:
                if fact.concept_qname != root:
                    continue
                if set(fact.dimensions) != {_PLAN_ENTITY_AXIS}:
                    continue
                if fact.dimensions[_PLAN_ENTITY_AXIS] != member:
                    continue
                if not isinstance(fact.value, (int, float)):
                    continue
                date = fact.instant_date if period_type == "instant" else fact.end_date
                if date and (latest is None or date > latest[0]):
                    latest = (date, float(fact.value))
            if latest is not None and (best is None or (latest[1], member) > best):
                best = (latest[1], member)
        return best[1] if best is not None else None

    def _plan_scoped_facts(self, member: str) -> tuple[XbrlFact, ...]:
        """Filing facts inside one plan entity context, re-based undimensioned.

        Facts dimensioned beyond the entity axis (the schedule mass)
        stay out; only the statement face is composed.
        """
        scoped: list[XbrlFact] = []
        for fact in self._kernel.facts:
            if not fact.dimensions:
                scoped.append(fact)
            elif (
                set(fact.dimensions) == {_PLAN_ENTITY_AXIS}
                and fact.dimensions[_PLAN_ENTITY_AXIS] == member
            ):
                scoped.append(replace(fact, dimensions={}))
        return tuple(scoped)

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
