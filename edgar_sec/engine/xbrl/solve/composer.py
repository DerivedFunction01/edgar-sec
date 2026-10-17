"""Algebraic statement graph composition and coordinate-based root discovery."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from edgar_sec.engine.xbrl.normalize.decomposer import decompose_concept
from edgar_sec.engine.xbrl.schema.models import CalculationArc, XbrlFact
from edgar_sec.engine.xbrl.solve.statement import (
    BalanceSheetGraph,
    CashFlowGraph,
    IncomeStatementGraph,
    StatementGraph,
    build_statement_graph,
)
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy


class StatementComposer:
    """Discovers statement roots via calculation topology and subatomic coordinates."""

    def __init__(
        self,
        facts: Sequence[XbrlFact],
        calculation_arcs: Sequence[CalculationArc],
        taxonomy: DomainTaxonomy,
        labels: Mapping[str, str] | None = None,
    ) -> None:
        self._facts = tuple(facts)
        self._arcs = tuple(calculation_arcs)
        self._taxonomy = taxonomy
        self._labels = dict(labels or {})

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
                decompose_concept(r, lex)[0].head in ("H_CASH", "H_FLOW")
                for r in dag_roots
            )
            else all_parents
        )

        matches: list[tuple[int, int, str]] = []
        for p in candidates:
            atom, _, _, _ = decompose_concept(p, lex)
            if atom.head not in ("H_CASH", "H_FLOW"):
                continue
            is_change = "M_CHANGE" in atom.modifiers
            priority = 0 if is_change else 1
            matches.append((priority, len(p.split(":")[-1]), p))

        if matches:
            matches.sort()
            return matches[0][2]
        return ""

    def find_income_statement_root(self) -> str:
        """Find the root concept for Statement of Operations via canonical sink."""
        lex = self._taxonomy.token_lexicon
        if not lex or not self._arcs:
            return ""

        all_parents = {a.parent_qname for a in self._arcs}
        candidates = all_parents

        matches: list[tuple[int, int, str]] = []
        for p in candidates:
            atom, _, _, _ = decompose_concept(p, lex)
            if atom.head not in ("H_INCOME", "H_PROFIT", "H_MARGIN", "H_LOSS"):
                continue
            if "M_COMPREHENSIVE" in atom.modifiers or "M_OCI" in atom.modifiers:
                continue
            if "M_NET_BOTTOMLINE" in atom.modifiers:
                priority = 0
            elif "M_OPERATING" in atom.modifiers:
                priority = 1
            elif "M_GROSS" in atom.modifiers or "M_GROSS_MARGIN" in atom.modifiers:
                priority = 2
            elif "M_PRETAX_OPERATING_MARGIN" in atom.modifiers:
                priority = 3
            else:
                priority = 4
            matches.append((priority, len(p.split(":")[-1]), p))

        if matches:
            matches.sort()
            return matches[0][2]
        return ""

    def find_balance_sheet_root(self) -> str:
        """Find the root concept for Balance Sheet via minimal asset coordinate."""
        lex = self._taxonomy.token_lexicon
        if not lex or not self._arcs:
            return ""

        all_parents = {a.parent_qname for a in self._arcs}
        dag_roots = self._dag_roots()
        candidates = (
            dag_roots
            if any(decompose_concept(r, lex)[0].head == "H_ASSET" for r in dag_roots)
            else all_parents
        )

        matches: list[tuple[int, int, str]] = []
        contra = {"M_CONTRA", "M_DEPRECIATION", "M_ALLOWANCE"}
        for p in candidates:
            atom, _, _, _ = decompose_concept(p, lex)
            if atom.head == "H_ASSET" and not any(m in atom.modifiers for m in contra):
                matches.append((len(atom.modifiers), len(p.split(":")[-1]), p))
            elif atom.head == "H_LIABILITY" and "M_EQUITY_TOTAL" in atom.modifiers:
                matches.append((10 + len(atom.modifiers), len(p.split(":")[-1]), p))

        if matches:
            matches.sort()
            return matches[0][2]
        return ""

    def _find_concept_by_atom(
        self,
        target_head: str,
        target_mods: set[str],
        excluded_mods: set[str] = frozenset(),
    ) -> str | None:
        lex = self._taxonomy.token_lexicon
        if not lex:
            return None
        all_parents = {a.parent_qname for a in self._arcs}
        all_concepts = all_parents | {a.child_qname for a in self._arcs}
        candidates: list[tuple[int, int, int, str]] = []
        for c in all_concepts:
            atom, _, _, _ = decompose_concept(c, lex)
            if atom.head == target_head and target_mods.issubset(atom.modifiers):
                if excluded_mods and any(m in atom.modifiers for m in excluded_mods):
                    continue
                extra_mods = len(atom.modifiers - target_mods)
                is_leaf = 1 if c not in all_parents else 0
                name_len = len(c.split(":")[-1])
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
        cfo_qname = self._find_concept_by_atom(
            "H_CASH", {"M_OPERATING", "V_NET"}
        ) or self._find_concept_by_atom("H_CASH", {"M_OPERATING"})
        cfi_qname = self._find_concept_by_atom(
            "H_CASH", {"M_INVESTING", "V_NET"}
        ) or self._find_concept_by_atom("H_CASH", {"M_INVESTING"})
        cff_qname = self._find_concept_by_atom(
            "H_CASH", {"M_FINANCING", "V_NET"}
        ) or self._find_concept_by_atom("H_CASH", {"M_FINANCING"})

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
        assets_qname = self._find_concept_by_atom(
            "H_ASSET",
            set(),
            {"M_CONTRA", "M_DEPRECIATION", "M_CURRENT", "M_NONCURRENT"},
        )
        liab_qname = self._find_concept_by_atom(
            "H_LIABILITY", set(), {"M_EQUITY_TOTAL", "M_CURRENT", "M_NONCURRENT"}
        )
        equity_qname = self._find_concept_by_atom("H_EQUITY", set())

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

    def compose_income_statement(
        self,
        period: str | None = None,
        year: int | str | None = None,
    ) -> IncomeStatementGraph:
        """Build IncomeStatementGraph auto-linking gross profit and operating income."""
        root = self.find_income_statement_root()
        gross_profit_qname = self._find_concept_by_atom(
            "H_INCOME", {"M_GROSS"}
        ) or self._find_concept_by_atom("H_INCOME", {"M_GROSS_MARGIN"})
        operating_inc_qname = self._find_concept_by_atom("H_INCOME", {"M_OPERATING"})

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
