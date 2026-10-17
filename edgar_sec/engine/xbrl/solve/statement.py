"""Algebraic statement graphs, rollups, and subatomic financial projections."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from edgar_sec.engine.xbrl.normalize.decomposer import decompose_concept
from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.schema.models import CalculationArc, XbrlFact
from edgar_sec.engine.xbrl.solve.antichain import AntiChainOutcome, AntiChainValidator
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy


@dataclass(frozen=True, slots=True)
class StatementNode:
    """Graph node in a statement hierarchy chained to underlying facts."""

    concept_qname: str
    atom: Atom
    label: str
    facts: tuple[XbrlFact, ...]
    value: float | None
    depth: int = 0
    weight: float = 1.0
    values: dict[str, float] = field(default_factory=dict)
    yoy_change: float | None = None
    yoy_pct: float | None = None


@dataclass(frozen=True, slots=True)
class StatementEdge:
    """Directed algebraic edge between statement concepts."""

    parent_qname: str
    child_qname: str
    weight: float = 1.0
    relation_type: str = "SUMMATION"
    order: float | None = None


class StatementGraph:
    """Algebraic relation graph over statement nodes and calculation arcs."""

    def __init__(
        self,
        statement_type: str,
        root_qname: str,
        nodes: dict[str, StatementNode],
        edges: Sequence[StatementEdge],
        calculation_arcs: Sequence[CalculationArc] = (),
        years: Sequence[str] = (),
    ) -> None:
        self.statement_type = statement_type
        self.root_qname = root_qname
        self.nodes = dict(nodes)
        self.edges = tuple(edges)
        self._calc_arcs = tuple(calculation_arcs)
        self.years = tuple(years)
        self._children: dict[str, list[StatementNode]] = {}
        self._parents: dict[str, list[StatementNode]] = {}
        for edge in self.edges:
            if edge.parent_qname in self.nodes and edge.child_qname in self.nodes:
                self._children.setdefault(edge.parent_qname, []).append(
                    self.nodes[edge.child_qname]
                )
                self._parents.setdefault(edge.child_qname, []).append(
                    self.nodes[edge.parent_qname]
                )

    @property
    def root(self) -> StatementNode | None:
        """Return the root statement node."""
        return self.nodes.get(self.root_qname)

    def children(self, concept_qname: str) -> tuple[StatementNode, ...]:
        """Return immediate children nodes rolling into this concept."""
        return tuple(self._children.get(concept_qname, ()))

    def parents(self, concept_qname: str) -> tuple[StatementNode, ...]:
        """Return immediate parent nodes that this concept rolls up into."""
        return tuple(self._parents.get(concept_qname, ()))

    def chain(self, concept_qname: str) -> tuple[StatementNode, ...]:
        """Return upward topological rollup chain from concept to root."""
        if concept_qname not in self.nodes:
            return ()
        path: list[StatementNode] = [self.nodes[concept_qname]]
        curr = concept_qname
        visited: set[str] = {curr}
        while curr != self.root_qname:
            parents = self._parents.get(curr, [])
            if not parents:
                break
            nxt = parents[0].concept_qname
            if nxt in visited:
                break
            visited.add(nxt)
            path.append(self.nodes[nxt])
            curr = nxt
        return tuple(path)

    def filter_year(self, year: int | str) -> StatementGraph:
        """Return a statement graph filtered to a single fiscal year."""
        yr_str = str(year)
        filtered_nodes: dict[str, StatementNode] = {}
        for k, node in self.nodes.items():
            val = node.values.get(yr_str)
            filtered_nodes[k] = StatementNode(
                concept_qname=node.concept_qname,
                atom=node.atom,
                label=node.label,
                facts=node.facts,
                value=val,
                depth=node.depth,
                weight=node.weight,
                values={yr_str: val} if val is not None else {},
                yoy_change=None,
                yoy_pct=None,
            )
        return self.__class__(
            statement_type=self.statement_type,
            root_qname=self.root_qname,
            nodes=filtered_nodes,
            edges=self.edges,
            calculation_arcs=self._calc_arcs,
            years=(yr_str,),
        )

    def verify_antichain(self) -> AntiChainOutcome:
        """Verify non-double-counting and exact summation balance."""
        raw_arcs = [
            (arc.parent_qname, arc.child_qname, arc.weight) for arc in self._calc_arcs
        ]
        validator = AntiChainValidator()
        children = self.children(self.root_qname)
        components = [node.concept_qname for node in children]
        weights = {
            edge.child_qname: edge.weight
            for edge in self.edges
            if edge.parent_qname == self.root_qname
        }
        values = {
            k: node.value for k, node in self.nodes.items() if node.value is not None
        }
        return validator.verify_non_double_counting(
            selected_concepts=components,
            calculation_arcs=raw_arcs,
            target_concept=self.root_qname,
            concept_values=values,
            concept_weights=weights,
        )


class IncomeStatementGraph(StatementGraph):
    """Algebraic graph for Statement of Operations with sub-graphs."""

    def __init__(
        self,
        statement_type: str,
        root_qname: str,
        nodes: dict[str, StatementNode],
        edges: Sequence[StatementEdge],
        calculation_arcs: Sequence[CalculationArc] = (),
        years: Sequence[str] = (),
        gross_profit_graph: StatementGraph | None = None,
        operating_income_graph: StatementGraph | None = None,
    ) -> None:
        super().__init__(
            statement_type, root_qname, nodes, edges, calculation_arcs, years
        )
        self.gross_profit_graph = gross_profit_graph
        self.operating_income_graph = operating_income_graph


class BalanceSheetGraph(StatementGraph):
    """Algebraic graph for Statement of Financial Position with sub-graphs."""

    def __init__(
        self,
        statement_type: str,
        root_qname: str,
        nodes: dict[str, StatementNode],
        edges: Sequence[StatementEdge],
        calculation_arcs: Sequence[CalculationArc] = (),
        years: Sequence[str] = (),
        assets_graph: StatementGraph | None = None,
        liabilities_graph: StatementGraph | None = None,
        equity_graph: StatementGraph | None = None,
    ) -> None:
        super().__init__(
            statement_type, root_qname, nodes, edges, calculation_arcs, years
        )
        self.assets_graph = assets_graph
        self.liabilities_graph = liabilities_graph
        self.equity_graph = equity_graph

    @property
    def total_assets(self) -> float | None:
        """Total assets reported on balance sheet."""
        return (
            self.assets_graph.root.value
            if self.assets_graph and self.assets_graph.root
            else None
        )

    @property
    def total_liabilities(self) -> float | None:
        """Total liabilities reported on balance sheet."""
        return (
            self.liabilities_graph.root.value
            if self.liabilities_graph and self.liabilities_graph.root
            else None
        )

    @property
    def total_equity(self) -> float | None:
        """Total stockholders equity reported on balance sheet."""
        return (
            self.equity_graph.root.value
            if self.equity_graph and self.equity_graph.root
            else None
        )

    @property
    def is_balanced(self) -> bool:
        """Verify the fundamental accounting identity: Assets = Liabilities + Equity."""
        a = self.total_assets
        l = self.total_liabilities
        e = self.total_equity
        if a is not None and l is not None and e is not None:
            return abs(a - (l + e)) < 1.0
        return False


class CashFlowGraph(StatementGraph):
    """Tripartite algebraic graph for Statement of Cash Flows."""

    def __init__(
        self,
        statement_type: str,
        root_qname: str,
        nodes: dict[str, StatementNode],
        edges: Sequence[StatementEdge],
        calculation_arcs: Sequence[CalculationArc] = (),
        years: Sequence[str] = (),
        operating: StatementGraph | None = None,
        investing: StatementGraph | None = None,
        financing: StatementGraph | None = None,
    ) -> None:
        super().__init__(
            statement_type, root_qname, nodes, edges, calculation_arcs, years
        )
        self.operating = operating
        self.investing = investing
        self.financing = financing

    @property
    def cfo(self) -> float | None:
        """Net cash provided by (used in) operating activities."""
        return (
            self.operating.root.value
            if self.operating and self.operating.root
            else None
        )

    @property
    def cfi(self) -> float | None:
        """Net cash provided by (used in) investing activities."""
        return (
            self.investing.root.value
            if self.investing and self.investing.root
            else None
        )

    @property
    def cff(self) -> float | None:
        """Net cash provided by (used in) financing activities."""
        return (
            self.financing.root.value
            if self.financing and self.financing.root
            else None
        )

    @property
    def net_core_cash_flow(self) -> float | None:
        """Sum of operating, investing, and financing cash flows."""
        o = self.cfo
        i = self.cfi
        f = self.cff
        if o is not None and i is not None and f is not None:
            return o + i + f
        return None


class AssetDecompositionGraph(StatementGraph):
    """Algebraic asset breakdown graph."""


class LiabilityDecompositionGraph(StatementGraph):
    """Algebraic liability breakdown graph."""


class EquityDecompositionGraph(StatementGraph):
    """Algebraic stockholders equity breakdown graph."""


class NetIncomeWaterfallGraph(StatementGraph):
    """Algebraic revenue-to-net-income waterfall graph."""


@dataclass(frozen=True, slots=True)
class DerivativePortfolioGraph:
    """Structured derivative portfolio exposure graph resolved dynamically."""

    gross_assets: float | None = None
    net_assets: float | None = None
    gross_liabilities: float | None = None
    net_liabilities: float | None = None
    notional_amount: float | None = None
    collateral_offsets: float | None = None
    master_netting_offsets: float | None = None
    positions: tuple[StatementNode, ...] = ()


@dataclass(frozen=True, slots=True)
class DebtStructureGraph:
    """Structured capital and debt obligations graph resolved dynamically."""

    total_debt: float | None = None
    current_debt: float | None = None
    long_term_debt: float | None = None
    leases: float | None = None
    positions: tuple[StatementNode, ...] = ()


def build_statement_graph(
    root_concept: str,
    statement_type: str,
    facts: Sequence[XbrlFact],
    arcs: Sequence[CalculationArc],
    taxonomy: DomainTaxonomy,
    labels: Mapping[str, str] | None = None,
    period_type: str | None = None,
    instant_date: str | None = None,
    end_date: str | None = None,
    year: int | str | None = None,
    graph_cls: type[StatementGraph] = StatementGraph,
    **extra_kwargs: Any,
) -> StatementGraph:
    """Build a StatementGraph from calculation arcs, facts, and coordinates."""
    raw_arcs = [(arc.parent_qname, arc.child_qname, arc.weight) for arc in arcs]
    reach = AntiChainValidator.build_reachability_map(raw_arcs)
    relevant_concepts = {root_concept} | reach.get(root_concept, set())

    lex = taxonomy.token_lexicon
    lbl_map = dict(labels or {})

    facts_by_concept: dict[str, list[XbrlFact]] = {}
    years_found: set[str] = set()
    target_year = str(year) if year is not None else None

    for f in facts:
        if f.concept_qname in relevant_concepts and not f.dimensions:
            yr = (f.instant_date if period_type == "instant" else f.end_date or "")[:4]
            if target_year and yr != target_year:
                continue
            if (
                period_type == "instant"
                and instant_date
                and f.instant_date != instant_date
            ):
                continue
            if period_type == "duration" and end_date and f.end_date != end_date:
                continue
            facts_by_concept.setdefault(f.concept_qname, []).append(f)
            if yr and len(yr) == 4 and yr.isdigit():
                years_found.add(yr)

    sorted_years = sorted(years_found)
    nodes: dict[str, StatementNode] = {}
    for c in relevant_concepts:
        atom = decompose_concept(c, lex)[0] if lex is not None else Atom("H_UNKNOWN")
        c_facts = tuple(facts_by_concept.get(c, ()))
        values_by_yr: dict[str, float] = {}
        for f in c_facts:
            if isinstance(f.value, (int, float)):
                yr = (f.instant_date if period_type == "instant" else f.end_date or "")[
                    :4
                ]
                if yr:
                    values_by_yr[yr] = float(f.value)

        latest_val = None
        yoy_change = None
        yoy_pct = None
        if sorted_years:
            latest_yr = sorted_years[-1]
            latest_val = values_by_yr.get(latest_yr)
            if len(sorted_years) >= 2:
                prior_yr = sorted_years[-2]
                prior_val = values_by_yr.get(prior_yr)
                if latest_val is not None and prior_val is not None:
                    yoy_change = latest_val - prior_val
                    if prior_val != 0:
                        yoy_pct = yoy_change / abs(prior_val)
        elif c_facts:
            num_facts = [f for f in c_facts if isinstance(f.value, (int, float))]
            if num_facts:
                latest_val = float(num_facts[0].value)  # type: ignore[arg-type]

        nodes[c] = StatementNode(
            concept_qname=c,
            atom=atom,
            label=lbl_map.get(c, c.split(":")[-1]),
            facts=c_facts,
            value=latest_val,
            values=values_by_yr,
            yoy_change=yoy_change,
            yoy_pct=yoy_pct,
        )

    edges = [
        StatementEdge(
            arc.parent_qname, arc.child_qname, arc.weight, "SUMMATION", arc.order
        )
        for arc in arcs
        if arc.parent_qname in relevant_concepts
        and arc.child_qname in relevant_concepts
    ]

    for _ in range(5):
        updated = False
        for c, node in list(nodes.items()):
            if node.value is None:
                child_edges = [e for e in edges if e.parent_qname == c]
                if child_edges and all(
                    nodes[e.child_qname].value is not None for e in child_edges
                ):
                    comp_val = sum(
                        e.weight * (nodes[e.child_qname].value or 0.0)
                        for e in child_edges
                    )
                    comp_years: dict[str, float] = {}
                    for yr in sorted_years:
                        if all(yr in nodes[e.child_qname].values for e in child_edges):
                            comp_years[yr] = sum(
                                e.weight * nodes[e.child_qname].values[yr]
                                for e in child_edges
                            )
                    c_yoy = None
                    c_pct = None
                    if (
                        len(sorted_years) >= 2
                        and sorted_years[-1] in comp_years
                        and sorted_years[-2] in comp_years
                    ):
                        c_yoy = (
                            comp_years[sorted_years[-1]] - comp_years[sorted_years[-2]]
                        )
                        if comp_years[sorted_years[-2]] != 0:
                            c_pct = c_yoy / abs(comp_years[sorted_years[-2]])
                    nodes[c] = StatementNode(
                        concept_qname=node.concept_qname,
                        atom=node.atom,
                        label=node.label,
                        facts=node.facts,
                        value=comp_val,
                        values=comp_years or node.values,
                        yoy_change=c_yoy,
                        yoy_pct=c_pct,
                    )
                    updated = True
        if not updated:
            break
    return graph_cls(
        statement_type=statement_type,
        root_qname=root_concept,
        nodes=nodes,
        edges=edges,
        calculation_arcs=arcs,
        years=sorted_years,
        **extra_kwargs,
    )
