"""Algebraic statement graph composition and coordinate-based root discovery."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from edgar_sec.engine.xbrl.normalize.decomposer import decompose_concept
from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.schema.models import (
    CalculationArc,
    XbrlFact,
    qname_local,
)
from edgar_sec.engine.xbrl.solve.antichain import AntiChainValidator
from edgar_sec.engine.xbrl.solve.bottomline import (
    bottomline_candidate,
    bottomline_rank,
    is_bottomline,
)
from edgar_sec.engine.xbrl.solve.statement import (
    BalanceSheetGraph,
    CashFlowGraph,
    IncomeStatementGraph,
    StatementGraph,
    StatementNode,
    build_statement_graph,
)
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy


_INCOME_HEADS = frozenset({"H_INCOME", "H_PROFIT", "H_MARGIN", "H_LOSS"})


class StatementComposer:
    """Discovers statement roots via calculation topology and subatomic coordinates."""

    def __init__(
        self,
        facts: Sequence[XbrlFact],
        calculation_arcs: Sequence[CalculationArc],
        taxonomy: DomainTaxonomy,
        labels: Mapping[str, str] | None = None,
        *,
        atom_resolver: Callable[[str], Atom | None] | None = None,
    ) -> None:
        self._facts = tuple(facts)
        self._arcs = tuple(calculation_arcs)
        self._taxonomy = taxonomy
        self._labels = dict(labels or {})
        self._atom_resolver = atom_resolver
        self._atom_cache: dict[str, Atom | None] = {}

    def _atom(self, qname: str) -> Atom | None:
        """Atom from the injected resolver, else lexicon decomposition."""
        if qname not in self._atom_cache:
            if self._atom_resolver is not None:
                self._atom_cache[qname] = self._atom_resolver(qname)
            else:
                lex = self._taxonomy.token_lexicon
                self._atom_cache[qname] = (
                    decompose_concept(qname, lex)[0] if lex is not None else None
                )
        return self._atom_cache[qname]

    def _dag_roots(self) -> set[str]:
        all_parents = {a.parent_qname for a in self._arcs}
        all_children = {a.child_qname for a in self._arcs}
        roots = all_parents - all_children
        return roots if roots else all_parents

    def find_cash_flow_root(self) -> str:
        """Find the root concept for Statement of Cash Flows via minimal coordinates."""
        lex = self._taxonomy.token_lexicon
        if not lex or not self._arcs:
            return ""

        all_parents = {a.parent_qname for a in self._arcs}
        dag_roots = self._dag_roots()
        candidates = (
            dag_roots
            if any(
                (atom := self._atom(r)) is not None
                and atom.head in ("H_CASH", "H_FLOW")
                for r in dag_roots
            )
            else all_parents
        )

        matches: list[tuple[int, int, str]] = []
        for p in candidates:
            atom = self._atom(p)
            if atom is None or atom.head not in ("H_CASH", "H_FLOW"):
                continue
            is_change = "M_CHANGE" in atom.modifiers
            priority = 0 if is_change else 1
            matches.append((priority, len(qname_local(p)), p))

        if matches:
            matches.sort()
            return matches[0][2]
        return ""

    def _revenue_tree_pool(self) -> set[str]:
        """Arc concepts atop a revenue line: ancestors of H_REVENUE concepts.

        Empty when no calculation path reaches a revenue concept.
        """
        concepts = {a.parent_qname for a in self._arcs} | {
            a.child_qname for a in self._arcs
        }
        revenue = {
            c
            for c in concepts
            if (atom := self._atom(c)) is not None and atom.head == "H_REVENUE"
        }
        if not revenue:
            return set()
        reach = AntiChainValidator.build_reachability_map(
            [(a.parent_qname, a.child_qname, a.weight) for a in self._arcs]
        )
        return {c for c in concepts if c in revenue or reach.get(c, set()) & revenue}

    def find_income_statement_root(self) -> str:
        """Find the root concept for Statement of Operations via calculation topology."""
        lex = self._taxonomy.token_lexicon
        if not lex or not self._arcs:
            return ""

        all_parents = {a.parent_qname for a in self._arcs}
        dag_roots = self._dag_roots()
        duration_parents = {
            f.concept_qname
            for f in self._facts
            if f.period_type == "duration" and f.concept_qname in all_parents
        }
        candidates = duration_parents if duration_parents else all_parents
        atoms = {
            concept: self._atom(concept)
            for concept in {a.parent_qname for a in self._arcs}
            | {a.child_qname for a in self._arcs}
        }
        root = self._income_root(candidates, self._arcs, atoms, dag_roots)
        pool = self._revenue_tree_pool()
        if pool and candidates & pool:
            confined_arcs = [a for a in self._arcs if a.parent_qname in pool]
            confined = bottomline_candidate(atoms, self._facts, confined_arcs)
            if confined is not None and confined in pool:
                return self._income_root(
                    candidates & pool, confined_arcs, atoms, dag_roots
                )
        return root

    def _income_root(
        self,
        candidates: set[str],
        arcs: list,
        atoms: dict,
        dag_roots: set[str],
    ) -> str:
        """Root over one candidate universe: matches ladder, bottomline override."""
        matches: list[tuple[int, int, int, str]] = []

        for p in candidates:
            atom = self._atom(p)
            if atom is None or atom.head not in _INCOME_HEADS:
                continue
            if "M_COMPREHENSIVE" in atom.modifiers or "M_OCI" in atom.modifiers:
                continue
            is_net = is_bottomline(atom)
            is_dag_root = p in dag_roots
            has_comprehensive_parent = any(
                a.child_qname == p
                and (parent_atom := self._atom(a.parent_qname)) is not None
                and bool({"M_COMPREHENSIVE", "M_OCI"} & parent_atom.modifiers)
                for a in arcs
            )

            if is_net and (is_dag_root or has_comprehensive_parent):
                priority = 0
            elif is_net:
                priority = 1
            elif is_dag_root:
                priority = 2
            elif "M_OPERATING" in atom.modifiers:
                priority = 3
            elif (
                "M_GROSS" in atom.modifiers
                or "M_GROSS_MARGIN" in atom.modifiers
                or "V_GROSS" in atom.modifiers
            ):
                priority = 4
            elif "M_PRETAX_OPERATING_MARGIN" in atom.modifiers:
                priority = 5
            else:
                priority = 6

            num_children = len([a for a in arcs if a.parent_qname == p])
            matches.append((priority, -num_children, len(qname_local(p)), p))

        bottomline = bottomline_candidate(atoms, self._facts, arcs)
        if not matches:
            return bottomline or ""
        matches.sort()
        winner = matches[0][3]
        if bottomline is not None:
            winner_rank = bottomline_rank(atoms.get(winner), winner)
            bottom_rank = bottomline_rank(atoms.get(bottomline), bottomline)
            if winner_rank is None or (
                bottom_rank is not None and bottom_rank < winner_rank
            ):
                return bottomline
        return winner

    def find_balance_sheet_root(self) -> str:
        """Find the root concept for Balance Sheet via minimal asset coordinate."""
        lex = self._taxonomy.token_lexicon
        if not lex or not self._arcs:
            return ""

        all_parents = {a.parent_qname for a in self._arcs}
        dag_roots = self._dag_roots()
        candidates = (
            dag_roots
            if any(
                (atom := self._atom(r)) is not None and atom.head == "H_ASSET"
                for r in dag_roots
            )
            else all_parents
        )

        matches: list[tuple[int, int, str]] = []
        contra = {"M_CONTRA", "M_DEPRECIATION", "M_ALLOWANCE"}
        for p in candidates:
            atom = self._atom(p)
            if atom is None:
                continue
            if atom.head == "H_ASSET" and not any(m in atom.modifiers for m in contra):
                matches.append((len(atom.modifiers), len(qname_local(p)), p))
            elif atom.head == "H_LIABILITY" and "M_EQUITY_TOTAL" in atom.modifiers:
                matches.append((10 + len(atom.modifiers), len(qname_local(p)), p))

        if matches:
            matches.sort()
            return matches[0][2]
        return ""

    def find_concept_by_atom(
        self,
        target_head: str,
        target_mods: set[str] | frozenset[str] = frozenset(),
        excluded_mods: set[str] | frozenset[str] = frozenset(),
    ) -> str | None:
        """Preferred arc concept in a coordinate subspace (fewest extras)."""
        lex = self._taxonomy.token_lexicon
        if not lex:
            return None
        all_parents = {a.parent_qname for a in self._arcs}
        all_concepts = all_parents | {a.child_qname for a in self._arcs}
        candidates: list[tuple[int, int, int, str]] = []
        for c in all_concepts:
            atom = self._atom(c)
            if atom is None or atom.head != target_head:
                continue
            if target_mods and not target_mods.issubset(atom.modifiers):
                continue
            if excluded_mods and any(m in atom.modifiers for m in excluded_mods):
                continue
            extra_mods = len(atom.modifiers - set(target_mods))
            is_leaf = 1 if c not in all_parents else 0
            name_len = len(qname_local(c))
            candidates.append((extra_mods, is_leaf, name_len, c))

        if candidates:
            candidates.sort()
            return candidates[0][3]
        return None

    def compose_cash_flow(
        self,
        period: str | None = None,
        year: int | str | None = None,
    ) -> CashFlowGraph:
        """Build tripartite CashFlowGraph auto-linking operating, investing, and financing."""
        root = self.find_cash_flow_root()
        cfo_qname = (
            self.find_concept_by_atom(
                "H_CASH", {"M_OPERATING", "V_NET"}, excluded_mods={"M_DISCONTINUED"}
            )
            or self.find_concept_by_atom(
                "H_CASH", {"M_OPERATING"}, excluded_mods={"M_DISCONTINUED"}
            )
            or self.find_concept_by_atom("H_CASH", {"M_OPERATING", "V_NET"})
            or self.find_concept_by_atom("H_CASH", {"M_OPERATING"})
        )
        cfi_qname = (
            self.find_concept_by_atom(
                "H_CASH", {"M_INVESTING", "V_NET"}, excluded_mods={"M_DISCONTINUED"}
            )
            or self.find_concept_by_atom(
                "H_CASH", {"M_INVESTING"}, excluded_mods={"M_DISCONTINUED"}
            )
            or self.find_concept_by_atom("H_CASH", {"M_INVESTING", "V_NET"})
            or self.find_concept_by_atom("H_CASH", {"M_INVESTING"})
        )
        cff_qname = (
            self.find_concept_by_atom(
                "H_CASH", {"M_FINANCING", "V_NET"}, excluded_mods={"M_DISCONTINUED"}
            )
            or self.find_concept_by_atom(
                "H_CASH", {"M_FINANCING"}, excluded_mods={"M_DISCONTINUED"}
            )
            or self.find_concept_by_atom("H_CASH", {"M_FINANCING", "V_NET"})
            or self.find_concept_by_atom("H_CASH", {"M_FINANCING"})
        )

        cfo_graph = (
            build_statement_graph(
                root_concept=cfo_qname,
                statement_type="Operating Cash Flows",
                facts=self._facts,
                arcs=self._arcs,
                taxonomy=self._taxonomy,
                labels=self._labels,
                period_type="duration",
                end_date=period,
                year=year,
                graph_cls=StatementGraph,
            )
            if cfo_qname
            else None
        )
        cfi_graph = (
            build_statement_graph(
                root_concept=cfi_qname,
                statement_type="Investing Cash Flows",
                facts=self._facts,
                arcs=self._arcs,
                taxonomy=self._taxonomy,
                labels=self._labels,
                period_type="duration",
                end_date=period,
                year=year,
                graph_cls=StatementGraph,
            )
            if cfi_qname
            else None
        )
        cff_graph = (
            build_statement_graph(
                root_concept=cff_qname,
                statement_type="Financing Cash Flows",
                facts=self._facts,
                arcs=self._arcs,
                taxonomy=self._taxonomy,
                labels=self._labels,
                period_type="duration",
                end_date=period,
                year=year,
                graph_cls=StatementGraph,
            )
            if cff_qname
            else None
        )

        return build_statement_graph(
            root_concept=root or (cfo_qname or ""),
            statement_type="Cash Flow Statement",
            facts=self._facts,
            arcs=self._arcs,
            taxonomy=self._taxonomy,
            labels=self._labels,
            period_type="duration",
            end_date=period,
            year=year,
            graph_cls=CashFlowGraph,
            operating=cfo_graph,
            investing=cfi_graph,
            financing=cff_graph,
        )  # type: ignore[return-value]

    def compose_balance_sheet(
        self,
        period: str | None = None,
        year: int | str | None = None,
    ) -> BalanceSheetGraph:
        """Build BalanceSheetGraph auto-linking assets, liabilities, and equity."""
        root = self.find_balance_sheet_root()
        assets_qname = self.find_concept_by_atom(
            "H_ASSET",
            set(),
            {"M_CONTRA", "M_DEPRECIATION", "M_CURRENT", "M_NONCURRENT"},
        )
        liab_qname = self.find_concept_by_atom(
            "H_LIABILITY", set(), {"M_EQUITY_TOTAL", "M_CURRENT", "M_NONCURRENT"}
        )
        equity_qname = self.find_concept_by_atom("H_EQUITY", set())
        if root and assets_qname and root != assets_qname:
            reach = AntiChainValidator.build_reachability_map(
                [(a.parent_qname, a.child_qname, a.weight) for a in self._arcs]
            )
            below = reach.get(root, set())
            sections = {q for q in (liab_qname, equity_qname) if q}
            if assets_qname not in below and not sections & below:
                root = assets_qname

        assets_graph = (
            build_statement_graph(
                root_concept=assets_qname or root,
                statement_type="Assets",
                facts=self._facts,
                arcs=self._arcs,
                taxonomy=self._taxonomy,
                labels=self._labels,
                period_type="instant",
                instant_date=period,
                year=year,
                graph_cls=StatementGraph,
            )
            if (assets_qname or root)
            else None
        )
        liab_graph = (
            build_statement_graph(
                root_concept=liab_qname,
                statement_type="Liabilities",
                facts=self._facts,
                arcs=self._arcs,
                taxonomy=self._taxonomy,
                labels=self._labels,
                period_type="instant",
                instant_date=period,
                year=year,
                graph_cls=StatementGraph,
            )
            if liab_qname
            else None
        )
        equity_graph = (
            build_statement_graph(
                root_concept=equity_qname,
                statement_type="Stockholders Equity",
                facts=self._facts,
                arcs=self._arcs,
                taxonomy=self._taxonomy,
                labels=self._labels,
                period_type="instant",
                instant_date=period,
                year=year,
                graph_cls=StatementGraph,
            )
            if equity_qname
            else None
        )

        return build_statement_graph(
            root_concept=root or (assets_qname or ""),
            statement_type="Balance Sheet",
            facts=self._facts,
            arcs=self._arcs,
            taxonomy=self._taxonomy,
            labels=self._labels,
            period_type="instant",
            instant_date=period,
            year=year,
            graph_cls=BalanceSheetGraph,
            assets_graph=assets_graph,
            liabilities_graph=liab_graph,
            equity_graph=equity_graph,
        )  # type: ignore[return-value]

    def _find_gross_profit_concept(self) -> str | None:
        lex = self._taxonomy.token_lexicon
        if not lex:
            return None
        found = self.find_concept_by_atom(
            "H_INCOME", {"M_GROSS"}
        ) or self.find_concept_by_atom("H_INCOME", {"M_GROSS_MARGIN"})
        if found:
            return found
        for parent in sorted({a.parent_qname for a in self._arcs}):
            parent_atom = self._atom(parent)
            if (
                parent_atom is None
                or parent_atom.head not in _INCOME_HEADS
                or "M_DISCONTINUED" in parent_atom.modifiers
            ):
                continue
            child_arcs = [a for a in self._arcs if a.parent_qname == parent]
            has_rev = any(
                a.weight > 0
                and (child := self._atom(a.child_qname)) is not None
                and child.head == "H_REVENUE"
                for a in child_arcs
            )
            has_cost = any(
                a.weight < 0
                and (child := self._atom(a.child_qname)) is not None
                and (child.head == "H_COST" or "M_COGS" in child.modifiers)
                for a in child_arcs
            )
            if has_rev and has_cost:
                return parent
        return None

    def _find_operating_income_concept(self) -> str | None:
        lex = self._taxonomy.token_lexicon
        if not lex:
            return None
        op = self.find_concept_by_atom("H_INCOME", {"M_OPERATING"})
        if op and any(
            fact.concept_qname == op and fact.period_type == "duration"
            for fact in self._facts
        ):
            return op
        for parent in sorted({a.parent_qname for a in self._arcs}):
            child_arcs = [a for a in self._arcs if a.parent_qname == parent]
            has_opex = any(
                a.weight < 0
                and (child := self._atom(a.child_qname)) is not None
                and any(m in ("M_OPERATING", "M_RD", "M_SGA") for m in child.modifiers)
                for a in child_arcs
            )
            atom = self._atom(parent)
            if atom is None:
                continue
            if (
                has_opex
                and "M_OPERATING" in atom.modifiers
                and atom.head in ("H_INCOME", "H_PROFIT", "H_LOSS")
                and any(
                    fact.concept_qname == parent and fact.period_type == "duration"
                    for fact in self._facts
                )
            ):
                return parent
        return None

    def compose_income_statement(
        self,
        period: str | None = None,
        year: int | str | None = None,
    ) -> IncomeStatementGraph:
        """Build IncomeStatementGraph auto-linking gross profit and operating income."""
        root = self.find_income_statement_root()
        gross_profit_qname = self._find_gross_profit_concept()
        operating_inc_qname = self._find_operating_income_concept()

        gross_graph = (
            build_statement_graph(
                root_concept=gross_profit_qname,
                statement_type="Gross Profit",
                facts=self._facts,
                arcs=self._arcs,
                taxonomy=self._taxonomy,
                labels=self._labels,
                period_type="duration",
                end_date=period,
                year=year,
                graph_cls=StatementGraph,
            )
            if gross_profit_qname
            else None
        )
        op_inc_graph = (
            build_statement_graph(
                root_concept=operating_inc_qname,
                statement_type="Operating Income",
                facts=self._facts,
                arcs=self._arcs,
                taxonomy=self._taxonomy,
                labels=self._labels,
                period_type="duration",
                end_date=period,
                year=year,
                graph_cls=StatementGraph,
            )
            if operating_inc_qname
            else None
        )

        return build_statement_graph(
            root_concept=root,
            statement_type="Income Statement",
            facts=self._facts,
            arcs=self._arcs,
            taxonomy=self._taxonomy,
            labels=self._labels,
            period_type="duration",
            end_date=period,
            year=year,
            graph_cls=IncomeStatementGraph,
            gross_profit_graph=gross_graph,
            operating_income_graph=op_inc_graph,
        )  # type: ignore[return-value]

    def resolve_subspace(
        self,
        target_head: str,
        target_mods: set[str] | frozenset[str] = frozenset(),
        excluded_mods: set[str] | frozenset[str] = frozenset(),
        *,
        is_instant: bool = False,
        year: int | str | None = None,
    ) -> float | None:
        """Resolve a coordinate subspace to an aggregate root or maximal antichain sum."""
        lex = self._taxonomy.token_lexicon
        if not lex:
            return None
        target_yr = str(year) if year is not None else None
        for f in self._facts:
            if f.dimensions or not isinstance(f.value, (int, float)):
                continue
            yr = (f.instant_date if is_instant else f.end_date or "")[:4]
            if target_yr and yr != target_yr:
                continue
            atom = self._atom(f.concept_qname)
            if atom is None:
                continue
            if atom.head == target_head and target_mods.issubset(atom.modifiers):
                if not excluded_mods or not (excluded_mods & atom.modifiers):
                    if len(atom.modifiers - target_mods) == 0:
                        return float(f.value)

        partition_vals: list[float] = []
        for f in self._facts:
            if f.dimensions or not isinstance(f.value, (int, float)):
                continue
            yr = (f.instant_date if is_instant else f.end_date or "")[:4]
            if target_yr and yr != target_yr:
                continue
            atom = self._atom(f.concept_qname)
            if atom is None:
                continue
            if atom.head == target_head and target_mods.issubset(atom.modifiers):
                if not excluded_mods or not (excluded_mods & atom.modifiers):
                    partition_vals.append(float(f.value))

        return max(partition_vals, key=abs) if partition_vals else None
