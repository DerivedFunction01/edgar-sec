"""Algebraic statement graph composition and coordinate-based root discovery."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from edgar_sec.engine.xbrl.normalize.decomposer import decompose_concept
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
    DebtStructureGraph,
    DerivativePortfolioGraph,
    IncomeStatementGraph,
    StatementGraph,
    StatementNode,
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
            matches.append((priority, len(qname_local(p)), p))

        if matches:
            matches.sort()
            return matches[0][2]
        return ""

    def find_income_statement_root(self) -> str:
        """Find the root concept for Statement of Operations via calculation topology."""
        lex = self._taxonomy.token_lexicon
        if not lex or not self._arcs:
            return ""

        all_parents = {a.parent_qname for a in self._arcs}
        dag_roots = self._dag_roots()
        matches: list[tuple[int, int, int, str]] = []

        duration_parents = {
            f.concept_qname
            for f in self._facts
            if f.period_type == "duration" and f.concept_qname in all_parents
        }
        candidates = duration_parents if duration_parents else all_parents

        for p in candidates:
            atom, val_type, _, _ = decompose_concept(p, lex)
            if atom.head not in ("H_INCOME", "H_PROFIT", "H_MARGIN", "H_LOSS"):
                continue
            if "M_COMPREHENSIVE" in atom.modifiers or "M_OCI" in atom.modifiers:
                continue
            is_net = is_bottomline(atom)
            is_dag_root = p in dag_roots
            has_comprehensive_parent = any(
                a.child_qname == p
                and bool(
                    {"M_COMPREHENSIVE", "M_OCI"}
                    & decompose_concept(a.parent_qname, lex)[0].modifiers
                )
                for a in self._arcs
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
                or val_type == "V_GROSS"
            ):
                priority = 4
            elif "M_PRETAX_OPERATING_MARGIN" in atom.modifiers:
                priority = 5
            else:
                priority = 6

            num_children = len([a for a in self._arcs if a.parent_qname == p])
            matches.append((priority, -num_children, len(qname_local(p)), p))

        atoms = {
            concept: decompose_concept(concept, lex)[0]
            for concept in {a.parent_qname for a in self._arcs}
            | {a.child_qname for a in self._arcs}
        }
        bottomline = bottomline_candidate(atoms, self._facts, self._arcs)
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
            if any(decompose_concept(r, lex)[0].head == "H_ASSET" for r in dag_roots)
            else all_parents
        )

        matches: list[tuple[int, int, str]] = []
        contra = {"M_CONTRA", "M_DEPRECIATION", "M_ALLOWANCE"}
        for p in candidates:
            atom, _, _, _ = decompose_concept(p, lex)
            if atom.head == "H_ASSET" and not any(m in atom.modifiers for m in contra):
                matches.append((len(atom.modifiers), len(qname_local(p)), p))
            elif atom.head == "H_LIABILITY" and "M_EQUITY_TOTAL" in atom.modifiers:
                matches.append((10 + len(atom.modifiers), len(qname_local(p)), p))

        if matches:
            matches.sort()
            return matches[0][2]
        return ""

    def _find_concept_by_atom(
        self,
        target_head: str,
        target_mods: set[str] | frozenset[str] = frozenset(),
        excluded_mods: set[str] | frozenset[str] = frozenset(),
        target_valence: str | None = None,
    ) -> str | None:
        lex = self._taxonomy.token_lexicon
        if not lex:
            return None
        all_parents = {a.parent_qname for a in self._arcs}
        all_concepts = all_parents | {a.child_qname for a in self._arcs}
        candidates: list[tuple[int, int, int, str]] = []
        for c in all_concepts:
            atom, val_type, _, _ = decompose_concept(c, lex)
            if atom.head == target_head:
                if target_mods and not target_mods.issubset(atom.modifiers):
                    continue
                if target_valence and val_type != target_valence:
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
            self._find_concept_by_atom(
                "H_CASH", {"M_OPERATING", "V_NET"}, excluded_mods={"M_DISCONTINUED"}
            )
            or self._find_concept_by_atom(
                "H_CASH", {"M_OPERATING"}, excluded_mods={"M_DISCONTINUED"}
            )
            or self._find_concept_by_atom("H_CASH", {"M_OPERATING", "V_NET"})
            or self._find_concept_by_atom("H_CASH", {"M_OPERATING"})
        )
        cfi_qname = (
            self._find_concept_by_atom(
                "H_CASH", {"M_INVESTING", "V_NET"}, excluded_mods={"M_DISCONTINUED"}
            )
            or self._find_concept_by_atom(
                "H_CASH", {"M_INVESTING"}, excluded_mods={"M_DISCONTINUED"}
            )
            or self._find_concept_by_atom("H_CASH", {"M_INVESTING", "V_NET"})
            or self._find_concept_by_atom("H_CASH", {"M_INVESTING"})
        )
        cff_qname = (
            self._find_concept_by_atom(
                "H_CASH", {"M_FINANCING", "V_NET"}, excluded_mods={"M_DISCONTINUED"}
            )
            or self._find_concept_by_atom(
                "H_CASH", {"M_FINANCING"}, excluded_mods={"M_DISCONTINUED"}
            )
            or self._find_concept_by_atom("H_CASH", {"M_FINANCING", "V_NET"})
            or self._find_concept_by_atom("H_CASH", {"M_FINANCING"})
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
        assets_qname = self._find_concept_by_atom(
            "H_ASSET",
            set(),
            {"M_CONTRA", "M_DEPRECIATION", "M_CURRENT", "M_NONCURRENT"},
        )
        liab_qname = self._find_concept_by_atom(
            "H_LIABILITY", set(), {"M_EQUITY_TOTAL", "M_CURRENT", "M_NONCURRENT"}
        )
        equity_qname = self._find_concept_by_atom("H_EQUITY", set())
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
        found = (
            self._find_concept_by_atom("H_INCOME", {"M_GROSS"})
            or self._find_concept_by_atom("H_INCOME", {"M_GROSS_MARGIN"})
            or self._find_concept_by_atom("H_INCOME", target_valence="V_GROSS")
        )
        if found:
            return found
        for parent in {a.parent_qname for a in self._arcs}:
            child_arcs = [a for a in self._arcs if a.parent_qname == parent]
            has_rev = any(
                a.weight > 0
                and decompose_concept(a.child_qname, lex)[0].head == "H_REVENUE"
                for a in child_arcs
            )
            has_cost = any(
                a.weight < 0
                and (
                    decompose_concept(a.child_qname, lex)[0].head == "H_COST"
                    or "M_COGS" in decompose_concept(a.child_qname, lex)[0].modifiers
                )
                for a in child_arcs
            )
            if has_rev and has_cost:
                return parent
        return None

    def _find_operating_income_concept(self) -> str | None:
        lex = self._taxonomy.token_lexicon
        if not lex:
            return None
        op = self._find_concept_by_atom("H_INCOME", {"M_OPERATING"})
        if op and any(
            fact.concept_qname == op and fact.period_type == "duration"
            for fact in self._facts
        ):
            return op
        for parent in sorted({a.parent_qname for a in self._arcs}):
            child_arcs = [a for a in self._arcs if a.parent_qname == parent]
            has_opex = any(
                a.weight < 0
                and any(
                    m in ("M_OPERATING", "M_RD", "M_SGA")
                    for m in decompose_concept(a.child_qname, lex)[0].modifiers
                )
                for a in child_arcs
            )
            atom = decompose_concept(parent, lex)[0]
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

    def _classify_risk(
        self,
        concept_qname: str,
        dimensions: Mapping[str, str],
    ) -> str:
        for mem in dimensions.values():
            risk = self._taxonomy.resolve_instrument_risk(mem)
            if risk:
                return risk

        lex = self._taxonomy.token_lexicon
        mods: set[str] = set()
        if lex:
            atom, _, _, _ = decompose_concept(concept_qname, lex)
            mods.update(atom.modifiers)
            for ax, mem in dimensions.items():
                mods.update(decompose_concept(ax, lex)[0].modifiers)
                mods.update(decompose_concept(mem, lex)[0].modifiers)

        mod_risk_map = {
            "M_RISK_IR": "interest_rate",
            "M_RISK_FX": "foreign_exchange",
            "M_RISK_CREDIT": "credit",
            "M_RISK_COMMODITY": "commodity",
            "M_RISK_EQUITY": "equity",
        }
        for mod, risk_type in mod_risk_map.items():
            if mod in mods:
                return risk_type

        return self._taxonomy.resolve_instrument_risk(concept_qname) or "other"

    def compose_derivative_portfolio(
        self,
        year: int | str | None = None,
    ) -> DerivativePortfolioGraph:
        """Resolve dynamic derivative portfolio exposures, risk buckets, and netting."""
        lex = self._taxonomy.token_lexicon
        target_year = str(year) if year is not None else None
        positions: list[StatementNode] = []
        by_risk: dict[str, list[StatementNode]] = {}
        risk_totals: dict[str, dict[str, float]] = {}

        gross_assets = None
        net_assets = None
        gross_liab = None
        net_liab = None
        notional = None
        collateral = None
        netting = None

        for f in self._facts:
            if not isinstance(f.value, (int, float)):
                continue
            yr = (f.instant_date or f.end_date or "")[:4]
            if target_year and yr != target_year:
                continue

            atom, val_type, _, _ = (
                decompose_concept(f.concept_qname, lex)
                if lex
                else (Atom("H_UNKNOWN"), "V_GROSS", (), 0)
            )
            is_deriv = "M_DERIVATIVE" in atom.modifiers or any(
                "Derivative" in ax for ax in f.dimensions
            )
            val = float(f.value)

            if not f.dimensions:
                if atom.head == "H_ASSET" and "M_DERIVATIVE" in atom.modifiers:
                    if "V_NET" in atom.modifiers or val_type == "V_NET":
                        net_assets = val if net_assets is None else max(net_assets, val)
                    else:
                        gross_assets = (
                            val if gross_assets is None else max(gross_assets, val)
                        )
                elif atom.head == "H_LIABILITY" and "M_DERIVATIVE" in atom.modifiers:
                    if "V_NET" in atom.modifiers or val_type == "V_NET":
                        net_liab = val if net_liab is None else max(net_liab, val)
                    else:
                        gross_liab = val if gross_liab is None else max(gross_liab, val)
                elif atom.head == "H_NOTIONAL":
                    notional = val if notional is None else max(notional, val)
                elif "M_CASH_COLLATERAL_OFFSET" in atom.modifiers:
                    collateral = val if collateral is None else max(collateral, val)
                elif "M_NOT_SUBJECT_TO_NETTING" in atom.modifiers:
                    netting = val if netting is None else max(netting, val)

            if is_deriv:
                risk_cat = self._classify_risk(f.concept_qname, f.dimensions)
                lbl = self._labels.get(f.concept_qname, qname_local(f.concept_qname))
                node = StatementNode(
                    concept_qname=f.concept_qname,
                    atom=atom,
                    label=lbl,
                    facts=(f,),
                    value=val,
                )
                positions.append(node)
                by_risk.setdefault(risk_cat, []).append(node)
                rt = risk_totals.setdefault(
                    risk_cat,
                    {"gross_assets": 0.0, "gross_liabilities": 0.0, "notional": 0.0},
                )
                if atom.head == "H_ASSET":
                    rt["gross_assets"] += val
                elif atom.head == "H_LIABILITY":
                    rt["gross_liabilities"] += val
                elif atom.head == "H_NOTIONAL":
                    rt["notional"] += val

        return DerivativePortfolioGraph(
            gross_assets=gross_assets,
            net_assets=net_assets,
            gross_liabilities=gross_liab,
            net_liabilities=net_liab,
            notional_amount=notional,
            collateral_offsets=collateral,
            master_netting_offsets=netting,
            positions=tuple(positions),
            by_risk={k: tuple(v) for k, v in by_risk.items()},
            risk_totals=risk_totals,
        )

    def compose_debt_structure(
        self,
        year: int | str | None = None,
    ) -> DebtStructureGraph:
        """Resolve capital debt structure, tranches, and maturity schedules."""
        lex = self._taxonomy.token_lexicon
        target_year = str(year) if year is not None else None
        positions: list[StatementNode] = []
        maturities: list[StatementNode] = []
        maturities_by_year: dict[str, float] = {}

        total_debt = None
        current_debt = None
        lt_debt = None
        cp = None
        leases = None

        for f in self._facts:
            if not isinstance(f.value, (int, float)):
                continue
            yr = (f.instant_date or f.end_date or "")[:4]
            if target_year and yr != target_year:
                continue

            atom, _, _, _ = (
                decompose_concept(f.concept_qname, lex)
                if lex
                else (Atom("H_UNKNOWN"), (), (), 0)
            )
            val = float(f.value)
            lbl = self._labels.get(f.concept_qname, qname_local(f.concept_qname))

            if atom.head == "H_LIABILITY":
                is_debt = bool(
                    atom.modifiers
                    & {"M_DEBT", "M_DEBT_BORROWING", "M_COMMERCIAL_PAPER"}
                )
                if is_debt:
                    if not f.dimensions:
                        if "M_COMMERCIAL_PAPER" in atom.modifiers:
                            cp = val if cp is None else max(cp, val)
                        if "M_CURRENT" in atom.modifiers:
                            current_debt = (
                                val if current_debt is None else max(current_debt, val)
                            )
                        elif "M_NONCURRENT" in atom.modifiers:
                            lt_debt = val if lt_debt is None else max(lt_debt, val)
                        elif "M_COMMERCIAL_PAPER" not in atom.modifiers:
                            total_debt = (
                                val if total_debt is None else max(total_debt, val)
                            )
                    positions.append(
                        StatementNode(
                            concept_qname=f.concept_qname,
                            atom=atom,
                            label=lbl,
                            facts=(f,),
                            value=val,
                        )
                    )
                elif (atom.modifiers & {"M_LEASE", "M_ROU_LEASE"}) and not f.dimensions:
                    leases = val if leases is None else max(leases, val)

            dim_mods: set[str] = set()
            if lex:
                for ax in f.dimensions:
                    dim_mods.update(decompose_concept(ax, lex)[0].modifiers)
            is_mat = bool(
                (atom.modifiers | dim_mods) & {"M_MATURITY", "M_MATURITY_HORIZON"}
            )
            if is_mat:
                mat_node = StatementNode(
                    concept_qname=f.concept_qname,
                    atom=atom,
                    label=lbl,
                    facts=(f,),
                    value=val,
                )
                maturities.append(mat_node)
                for mem in f.dimensions.values():
                    mem_yr = mem[-4:]
                    if mem_yr.isdigit():
                        maturities_by_year[mem_yr] = val

        if total_debt is None:
            parts = [p for p in (current_debt, lt_debt) if p is not None]
            if parts:
                total_debt = sum(parts)
            elif cp is not None:
                total_debt = cp

        return DebtStructureGraph(
            total_debt=total_debt,
            current_debt=current_debt,
            long_term_debt=lt_debt,
            commercial_paper=cp,
            leases=leases,
            positions=tuple(positions),
            maturities=tuple(maturities),
            maturities_by_year=maturities_by_year,
        )

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
            atom, _, _, _ = decompose_concept(f.concept_qname, lex)
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
            atom, _, _, _ = decompose_concept(f.concept_qname, lex)
            if atom.head == target_head and target_mods.issubset(atom.modifiers):
                if not excluded_mods or not (excluded_mods & atom.modifiers):
                    partition_vals.append(float(f.value))

        return max(partition_vals, key=abs) if partition_vals else None
