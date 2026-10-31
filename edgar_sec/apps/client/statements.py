"""Statement views as coordinate presets over display facts.

Roots are resolved by coordinate rules over the Step 3 display
records (the tokenizer service covers arc-only concepts); order and
rollup come from the engine statement graph builder, as before.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from edgar_sec.apps.client.facts import DisplayRecord
from edgar_sec.apps.client.equity_rollforward import build_equity_rollforward
from edgar_sec.apps.client.views import EquityRollforwardView, StatementView
from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.schema.models import (
    CalculationArc,
    ConceptDeclaration,
    DefinitionArc,
    XbrlFact,
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
    build_statement_graph,
)
from edgar_sec.engine.xbrl.solve.tokenizer import ConceptTokenizer
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy

_CONTRA = {"M_CONTRA", "M_DEPRECIATION", "M_ALLOWANCE"}


class XbrlStatements:
    """Statement factory for operations, balance sheet, cash flows, and equity."""

    def __init__(
        self,
        facts: Sequence[XbrlFact],
        calculation_arcs: Sequence[CalculationArc],
        taxonomy: DomainTaxonomy,
        labels: Mapping[str, str] | None = None,
        *,
        records: Mapping[str, DisplayRecord] | None = None,
        declarations: Mapping[str, ConceptDeclaration] | None = None,
        definition_arcs: Sequence[DefinitionArc] = (),
    ) -> None:
        self._facts = tuple(facts)
        self._arcs = tuple(calculation_arcs)
        self._definition_arcs = tuple(definition_arcs)
        self._taxonomy = taxonomy
        self._labels = dict(labels or {})
        self._records = dict(records or {})
        self._declarations = dict(declarations or {})
        self._tokenizer = (
            ConceptTokenizer(taxonomy) if taxonomy.token_lexicon is not None else None
        )
        self._atom_cache: dict[str, Atom | None] = {}

    def _atom(self, qname: str) -> Atom | None:
        """Atom for a concept: the display record, else the tokenizer."""
        record = self._records.get(qname)
        if record is not None:
            return record.atom
        if qname not in self._atom_cache:
            if self._tokenizer is None:
                self._atom_cache[qname] = None
            else:
                tokenized = self._tokenizer.tokenize(
                    qname, self._declarations.get(qname)
                )
                self._atom_cache[qname] = tokenized.atom
        return self._atom_cache[qname]

    def _head(self, qname: str) -> str:
        atom = self._atom(qname)
        return atom.head if atom else ""

    def _mods(self, qname: str) -> set[str]:
        atom = self._atom(qname)
        return set(atom.modifiers) if atom else set()

    def _dag_roots(self) -> set[str]:
        parents = {a.parent_qname for a in self._arcs}
        children = {a.child_qname for a in self._arcs}
        roots = parents - children
        return roots if roots else parents

    def _find_concept_by_atom(
        self,
        target_head: str,
        target_mods: frozenset[str] = frozenset(),
        excluded_mods: frozenset[str] = frozenset(),
    ) -> str | None:
        """Preferred arc concept in a coordinate subspace (fewest extras)."""
        if self._tokenizer is None:
            return None
        parents = {a.parent_qname for a in self._arcs}
        candidates: list[tuple[int, int, int, str]] = []
        for concept in parents | {a.child_qname for a in self._arcs}:
            atom = self._atom(concept)
            if atom is None or atom.head != target_head:
                continue
            if not target_mods.issubset(atom.modifiers):
                continue
            if excluded_mods & atom.modifiers:
                continue
            extra = len(atom.modifiers - target_mods)
            is_leaf = 1 if concept not in parents else 0
            candidates.append((extra, is_leaf, len(concept.split(":")[-1]), concept))
        if not candidates:
            return None
        candidates.sort()
        return candidates[0][3]

    def _cash_flow_root(self) -> str:
        if self._tokenizer is None or not self._arcs:
            return ""
        parents = {a.parent_qname for a in self._arcs}
        dag_roots = self._dag_roots()
        candidates = (
            dag_roots
            if any(self._head(r) in ("H_CASH", "H_FLOW") for r in dag_roots)
            else parents
        )
        matches: list[tuple[int, int, str]] = []
        for concept in candidates:
            atom = self._atom(concept)
            if atom is None or atom.head not in ("H_CASH", "H_FLOW"):
                continue
            priority = 0 if "M_CHANGE" in atom.modifiers else 1
            matches.append((priority, len(concept.split(":")[-1]), concept))
        if not matches:
            return ""
        matches.sort()
        return matches[0][2]

    def _balance_sheet_root(self) -> str:
        if self._tokenizer is None or not self._arcs:
            return ""
        parents = {a.parent_qname for a in self._arcs}
        dag_roots = self._dag_roots()
        candidates = (
            dag_roots if any(self._head(r) == "H_ASSET" for r in dag_roots) else parents
        )
        matches: list[tuple[int, int, str]] = []
        for concept in candidates:
            atom = self._atom(concept)
            if atom is None:
                continue
            if atom.head == "H_ASSET" and not (_CONTRA & atom.modifiers):
                matches.append(
                    (len(atom.modifiers), len(concept.split(":")[-1]), concept)
                )
            elif atom.head == "H_LIABILITY" and "M_EQUITY_TOTAL" in atom.modifiers:
                matches.append(
                    (10 + len(atom.modifiers), len(concept.split(":")[-1]), concept)
                )
        if not matches:
            return ""
        matches.sort()
        return matches[0][2]

    def _income_statement_root(self) -> str:
        if self._tokenizer is None or not self._arcs:
            return ""
        parents = {a.parent_qname for a in self._arcs}
        dag_roots = self._dag_roots()
        duration_parents = {
            f.concept_qname
            for f in self._facts
            if f.period_type == "duration" and f.concept_qname in parents
        }
        candidates = duration_parents if duration_parents else parents
        matches: list[tuple[int, int, int, str]] = []
        for concept in candidates:
            atom = self._atom(concept)
            if atom is None or atom.head not in (
                "H_INCOME",
                "H_PROFIT",
                "H_MARGIN",
                "H_LOSS",
            ):
                continue
            if "M_COMPREHENSIVE" in atom.modifiers or "M_OCI" in atom.modifiers:
                continue
            is_net = is_bottomline(atom)
            has_comp_parent = any(
                a.child_qname == concept
                and bool({"M_COMPREHENSIVE", "M_OCI"} & self._mods(a.parent_qname))
                for a in self._arcs
            )
            if is_net and (concept in dag_roots or has_comp_parent):
                priority = 0
            elif is_net:
                priority = 1
            elif concept in dag_roots:
                priority = 2
            elif "M_OPERATING" in atom.modifiers:
                priority = 3
            elif {"M_GROSS", "M_GROSS_MARGIN", "V_GROSS"} & atom.modifiers:
                priority = 4
            elif "M_PRETAX_OPERATING_MARGIN" in atom.modifiers:
                priority = 5
            else:
                priority = 6
            num_children = len([a for a in self._arcs if a.parent_qname == concept])
            matches.append(
                (priority, -num_children, len(concept.split(":")[-1]), concept)
            )
        atoms = {
            concept: self._atom(concept)
            for concept in {a.parent_qname for a in self._arcs}
            | {a.child_qname for a in self._arcs}
        }
        bottomline = (
            bottomline_candidate(atoms, self._facts, self._arcs)
            if self._tokenizer is not None
            else None
        )
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

    def _gross_profit_concept(self) -> str | None:
        """Gross profit root: the coordinate subspace, else a rev/cost parent."""
        if self._tokenizer is None:
            return None
        found = self._find_concept_by_atom(
            "H_INCOME", frozenset({"M_GROSS"})
        ) or self._find_concept_by_atom("H_INCOME", frozenset({"M_GROSS_MARGIN"}))
        if found:
            return found
        for parent in sorted({a.parent_qname for a in self._arcs}):
            child_arcs = [a for a in self._arcs if a.parent_qname == parent]
            has_rev = any(
                a.weight > 0 and self._head(a.child_qname) == "H_REVENUE"
                for a in child_arcs
            )
            has_cost = any(
                a.weight < 0
                and (
                    self._head(a.child_qname) == "H_COST"
                    or "M_COGS" in self._mods(a.child_qname)
                )
                for a in child_arcs
            )
            if has_rev and has_cost:
                return parent
        return None

    def _operating_income_concept(self) -> str | None:
        """Operating income root: the subspace, else an opex parent."""
        if self._tokenizer is None:
            return None
        found = self._find_concept_by_atom("H_INCOME", frozenset({"M_OPERATING"}))
        if found:
            return found
        for parent in sorted({a.parent_qname for a in self._arcs}):
            child_arcs = [a for a in self._arcs if a.parent_qname == parent]
            has_opex = any(
                a.weight < 0
                and bool({"M_OPERATING", "M_RD", "M_SGA"} & self._mods(a.child_qname))
                for a in child_arcs
            )
            if has_opex and self._head(parent) in ("H_INCOME", "H_PROFIT", "H_LOSS"):
                return parent
        return None

    def _build(self, **kwargs: object) -> StatementGraph:
        return build_statement_graph(
            facts=self._facts,
            arcs=self._arcs,
            taxonomy=self._taxonomy,
            labels=self._labels,
            **kwargs,  # type: ignore[arg-type]
        )

    def income_statement(
        self,
        period: str | None = None,
        year: int | str | None = None,
    ) -> StatementView:
        """Construct the algebraic Statement of Operations rollup view."""
        gross_qname = self._gross_profit_concept()
        op_qname = self._operating_income_concept()
        gross_graph = (
            self._build(
                root_concept=gross_qname,
                statement_type="Gross Profit",
                period_type="duration",
                end_date=period,
                year=year,
                graph_cls=StatementGraph,
            )
            if gross_qname
            else None
        )
        op_graph = (
            self._build(
                root_concept=op_qname,
                statement_type="Operating Income",
                period_type="duration",
                end_date=period,
                year=year,
                graph_cls=StatementGraph,
            )
            if op_qname
            else None
        )
        graph = self._build(
            root_concept=self._income_statement_root(),
            statement_type="Income Statement",
            period_type="duration",
            end_date=period,
            year=year,
            graph_cls=IncomeStatementGraph,
            gross_profit_graph=gross_graph,
            operating_income_graph=op_graph,
        )
        return StatementView(graph)  # type: ignore[arg-type]

    def balance_sheet(
        self,
        period: str | None = None,
        year: int | str | None = None,
    ) -> StatementView:
        """Construct the algebraic Balance Sheet rollup view."""
        root = self._balance_sheet_root()
        assets_qname = self._find_concept_by_atom(
            "H_ASSET",
            frozenset(),
            frozenset({"M_CONTRA", "M_DEPRECIATION", "M_CURRENT", "M_NONCURRENT"}),
        )
        liab_qname = self._find_concept_by_atom(
            "H_LIABILITY",
            frozenset(),
            frozenset({"M_EQUITY_TOTAL", "M_CURRENT", "M_NONCURRENT"}),
        )
        equity_qname = self._find_concept_by_atom("H_EQUITY", frozenset())
        if root and assets_qname and root != assets_qname:
            reach = AntiChainValidator.build_reachability_map(
                [(a.parent_qname, a.child_qname, a.weight) for a in self._arcs]
            )
            below = reach.get(root, set())
            sections = {q for q in (liab_qname, equity_qname) if q}
            if assets_qname not in below and not sections & below:
                root = assets_qname
        assets_graph = (
            self._build(
                root_concept=assets_qname or root,
                statement_type="Assets",
                period_type="instant",
                instant_date=period,
                year=year,
                graph_cls=StatementGraph,
            )
            if (assets_qname or root)
            else None
        )
        liab_graph = (
            self._build(
                root_concept=liab_qname,
                statement_type="Liabilities",
                period_type="instant",
                instant_date=period,
                year=year,
                graph_cls=StatementGraph,
            )
            if liab_qname
            else None
        )
        equity_graph = (
            self._build(
                root_concept=equity_qname,
                statement_type="Stockholders Equity",
                period_type="instant",
                instant_date=period,
                year=year,
                graph_cls=StatementGraph,
            )
            if equity_qname
            else None
        )
        graph = self._build(
            root_concept=root or (assets_qname or ""),
            statement_type="Balance Sheet",
            period_type="instant",
            instant_date=period,
            year=year,
            graph_cls=BalanceSheetGraph,
            assets_graph=assets_graph,
            liabilities_graph=liab_graph,
            equity_graph=equity_graph,
        )
        return StatementView(graph)  # type: ignore[arg-type]

    def cash_flow_statement(
        self,
        period: str | None = None,
        year: int | str | None = None,
    ) -> StatementView:
        """Construct the algebraic Statement of Cash Flows rollup view."""
        root = self._cash_flow_root()
        sections: dict[str, StatementGraph | None] = {}
        qnames: dict[str, str | None] = {}
        for key, mod, label in (
            ("operating", "M_OPERATING", "Operating Cash Flows"),
            ("investing", "M_INVESTING", "Investing Cash Flows"),
            ("financing", "M_FINANCING", "Financing Cash Flows"),
        ):
            qname = (
                self._find_concept_by_atom(
                    "H_CASH",
                    frozenset({mod, "V_NET"}),
                    frozenset({"M_DISCONTINUED"}),
                )
                or self._find_concept_by_atom(
                    "H_CASH",
                    frozenset({mod}),
                    frozenset({"M_DISCONTINUED"}),
                )
                or self._find_concept_by_atom("H_CASH", frozenset({mod, "V_NET"}))
                or self._find_concept_by_atom("H_CASH", frozenset({mod}))
            )
            qnames[key] = qname
            sections[key] = (
                self._build(
                    root_concept=qname,
                    statement_type=label,
                    period_type="duration",
                    end_date=period,
                    year=year,
                    graph_cls=StatementGraph,
                )
                if qname
                else None
            )
        graph = self._build(
            root_concept=root or (qnames["operating"] or ""),
            statement_type="Cash Flow Statement",
            period_type="duration",
            end_date=period,
            year=year,
            graph_cls=CashFlowGraph,
            operating=sections["operating"],
            investing=sections["investing"],
            financing=sections["financing"],
        )
        return StatementView(graph)  # type: ignore[arg-type]

    def equity_rollforward(
        self,
        member_qname: str | None = None,
        year: int | str | None = None,
    ) -> EquityRollforwardView:
        """Construct the statement of changes in equity, verified by identity."""
        graph = build_equity_rollforward(
            self._facts,
            self._records,
            self._taxonomy,
            self._labels,
            year,
            member_qname=member_qname,
            definition_arcs=self._definition_arcs,
        )
        return EquityRollforwardView(graph)
