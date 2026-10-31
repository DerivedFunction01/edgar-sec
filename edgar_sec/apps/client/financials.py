"""Algebraic financial aggregates, multi-year YoY series, and projections."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from edgar_sec.apps.client.composition import ChainTerms, CompositionResult
from edgar_sec.apps.client.facts import DisplayRecord, build_display_records
from edgar_sec.apps.client.equity_rollforward import build_equity_rollforward
from edgar_sec.apps.client.rollforwards import (
    build_level3_rollforward,
    build_pension_funded_status,
)
from edgar_sec.apps.client.topics import (
    build_cash_rollforward,
    build_debt_structure,
    build_derivative_portfolio,
    build_segment_breakdown,
)
from edgar_sec.apps.client.views import (
    CashRollforwardView,
    DebtStructureView,
    DerivativePortfolioView,
    EquityRollforwardView,
    Level3RollforwardView,
    PensionFundedStatusView,
    SegmentBreakdownView,
)
from edgar_sec.engine.xbrl.normalize.normalization import normalize_time_coordinate
from edgar_sec.engine.xbrl.schema.models import CalculationArc, DefinitionArc, XbrlFact
from edgar_sec.engine.xbrl.solve.composer import StatementComposer
from edgar_sec.engine.xbrl.solve.statement import period_rank
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy


def _span_length_class(fact: XbrlFact) -> str | None:
    """Length class of a fact's span; None when the fact carries no span."""
    if not fact.start_date or not fact.end_date:
        return None
    return normalize_time_coordinate(
        fact.period_type, fact.instant_date, fact.start_date, fact.end_date
    ).length_class


class XbrlFinancials:
    """Algebraic financial aggregates, multi-year YoY series, and projections."""

    def __init__(
        self,
        facts: Sequence[XbrlFact],
        calculation_arcs: Sequence[CalculationArc],
        taxonomy: DomainTaxonomy,
        labels: Mapping[str, str] | None = None,
        *,
        display_records: Mapping[str, DisplayRecord] | None = None,
        composition_resolver: Callable[[ChainTerms, int | None], CompositionResult]
        | None = None,
        definition_arcs: Sequence[DefinitionArc] = (),
    ) -> None:
        self._facts = tuple(facts)
        self._arcs = tuple(calculation_arcs)
        self._definition_arcs = tuple(definition_arcs)
        self._taxonomy = taxonomy
        self._labels = dict(labels or {})
        self._records = (
            dict(display_records)
            if display_records is not None
            else build_display_records(self._facts, self._taxonomy)
        )
        self._composition_resolver = composition_resolver
        self._composer = StatementComposer(
            self._facts, self._arcs, self._taxonomy, self._labels
        )

    def _scalar(
        self,
        target_head: str,
        target_mods: set[str] | frozenset[str] = frozenset(),
        excluded_mods: set[str] | frozenset[str] = frozenset(),
        *,
        is_instant: bool = False,
        year: int | str | None = None,
        valence: str | None = None,
        is_monetary: bool = True,
        prefer_bare: bool = False,
        length_class: str = "ANNUAL",
    ) -> float | None:
        series = self._series(
            target_head,
            target_mods,
            excluded_mods,
            is_instant=is_instant,
            valence=valence,
            is_monetary=is_monetary,
            prefer_bare=prefer_bare,
            length_class=length_class,
        )
        if year:
            return series.get(str(year))
        if not series:
            return None
        sorted_years = sorted(series.keys())
        return series[sorted_years[-1]]

    def _series(
        self,
        target_head: str,
        target_mods: set[str] | frozenset[str] = frozenset(),
        excluded_mods: set[str] | frozenset[str] = frozenset(),
        *,
        is_instant: bool = False,
        valence: str | None = None,
        is_monetary: bool = True,
        prefer_bare: bool = False,
        length_class: str = "ANNUAL",
    ) -> dict[str, float]:
        lex = self._taxonomy.token_lexicon
        if lex is None:
            return {}
        best: dict[tuple[str, str], tuple[tuple[int, int], float, int]] = {}
        for f in self._facts:
            if f.dimensions or not isinstance(f.value, (int, float)):
                continue
            span_class = _span_length_class(f)
            if span_class is not None and span_class != length_class:
                continue
            if is_monetary and f.unit in ("pure", "shares", "item", "ratio"):
                continue
            record = self._records.get(f.concept_qname)
            if record is None:
                continue
            atom = record.atom
            if atom.head == target_head and target_mods.issubset(atom.modifiers):
                if excluded_mods and any(m in atom.modifiers for m in excluded_mods):
                    continue
                if valence and valence not in atom.modifiers:
                    continue
                dt = f.instant_date if is_instant else f.end_date
                if not dt:
                    continue
                yr = dt[:4]
                if len(yr) == 4 and yr.isdigit():
                    key = (f.concept_qname, yr)
                    rank = period_rank(f)
                    if key not in best or rank > best[key][0]:
                        best[key] = (rank, float(f.value), len(atom.modifiers))

        by_year: dict[str, tuple[int, float, float]] = {}
        for (_qname, yr), (_rank, val, nmods) in best.items():
            cand = (nmods, -abs(val), val)
            if yr not in by_year:
                by_year[yr] = cand
            elif prefer_bare and cand < by_year[yr]:
                by_year[yr] = cand
            elif not prefer_bare and abs(val) > abs(by_year[yr][2]):
                by_year[yr] = cand
        return {yr: cand[2] for yr, cand in by_year.items()}

    def _yoy(
        self,
        target_head: str,
        target_mods: set[str] | frozenset[str] = frozenset(),
        excluded_mods: set[str] | frozenset[str] = frozenset(),
        *,
        is_instant: bool = False,
        valence: str | None = None,
        prefer_bare: bool = False,
        length_class: str = "ANNUAL",
    ) -> tuple[float, float] | None:
        series = self._series(
            target_head,
            target_mods,
            excluded_mods,
            is_instant=is_instant,
            valence=valence,
            prefer_bare=prefer_bare,
            length_class=length_class,
        )
        years = sorted(series.keys())
        if len(years) < 2:
            return None
        curr, prior = series[years[-1]], series[years[-2]]
        delta = curr - prior
        pct = delta / abs(prior) if prior != 0 else 0.0
        return delta, pct

    @property
    def revenue(self) -> float | None:
        inc = self._composer.compose_income_statement()
        if inc.gross_profit_graph and inc.gross_profit_graph.root:
            for child in inc.gross_profit_graph.children(
                inc.gross_profit_graph.root.concept_qname
            ):
                if child.atom.head == "H_REVENUE" and child.value is not None:
                    return child.value
        return self._scalar("H_REVENUE")

    @property
    def revenue_series(self) -> dict[str, float]:
        return self._series("H_REVENUE")

    @property
    def revenue_yoy(self) -> tuple[float, float] | None:
        return self._yoy("H_REVENUE")

    @property
    def gross_profit(self) -> float | None:
        inc = self._composer.compose_income_statement()
        if inc.gross_profit is not None:
            return inc.gross_profit
        return (
            self._scalar("H_INCOME", {"M_GROSS"})
            or self._scalar("H_INCOME", {"M_GROSS_MARGIN"})
            or self._scalar("H_INCOME", valence="V_GROSS")
        )

    @property
    def gross_profit_series(self) -> dict[str, float]:
        return (
            self._series("H_INCOME", {"M_GROSS"})
            or self._series("H_INCOME", {"M_GROSS_MARGIN"})
            or self._series("H_INCOME", valence="V_GROSS")
        )

    @property
    def gross_profit_yoy(self) -> tuple[float, float] | None:
        return (
            self._yoy("H_INCOME", {"M_GROSS"})
            or self._yoy("H_INCOME", {"M_GROSS_MARGIN"})
            or self._yoy("H_INCOME", valence="V_GROSS")
        )

    @property
    def operating_income(self) -> float | None:
        inc = self._composer.compose_income_statement()
        if inc.operating_income is not None:
            return inc.operating_income
        return self._scalar("H_INCOME", {"M_OPERATING"})

    @property
    def operating_income_series(self) -> dict[str, float]:
        return self._series("H_INCOME", {"M_OPERATING"})

    @property
    def operating_income_yoy(self) -> tuple[float, float] | None:
        return self._yoy("H_INCOME", {"M_OPERATING"})

    @property
    def net_income(self) -> float | None:
        inc = self._composer.compose_income_statement()
        if inc.net_income is not None:
            return inc.net_income
        return self._scalar(
            "H_INCOME",
            {"M_NET_BOTTOMLINE"},
            {"M_NONCONTROLLING_INTEREST", "M_COMMON", "V_BASIC", "V_DILUTED"},
        ) or self._scalar("H_INCOME", {"V_NET"})

    def _concept_series(
        self, qname: str, length_class: str = "ANNUAL"
    ) -> dict[str, float]:
        """One concept's values by year, longest span then finest decimals."""
        best: dict[str, tuple[tuple[int, int], float]] = {}
        for f in self._facts:
            if f.concept_qname != qname or f.dimensions:
                continue
            if not isinstance(f.value, (int, float)):
                continue
            span_class = _span_length_class(f)
            if span_class is not None and span_class != length_class:
                continue
            if f.unit in ("pure", "shares", "item", "ratio"):
                continue
            dt = f.instant_date or f.end_date
            if not dt:
                continue
            yr = dt[:4]
            rank = period_rank(f)
            if yr not in best or rank > best[yr][0]:
                best[yr] = (rank, float(f.value))
        return {yr: val for yr, (_rank, val) in best.items()}

    @property
    def net_income_series(self) -> dict[str, float]:
        root = self._composer.compose_income_statement().root_qname
        rooted = self._concept_series(root) if root else {}
        return (
            rooted
            or self._series(
                "H_INCOME",
                {"M_NET_BOTTOMLINE"},
                {"M_NONCONTROLLING_INTEREST", "M_COMMON", "V_BASIC", "V_DILUTED"},
            )
            or self._series("H_INCOME", {"M_NET_BOTTOMLINE"})
        )

    @property
    def net_income_yoy(self) -> tuple[float, float] | None:
        return self._yoy("H_INCOME", {"M_NET_BOTTOMLINE"})

    @property
    def total_assets(self) -> float | None:
        bs = self._composer.compose_balance_sheet()
        if bs.total_assets is not None:
            return bs.total_assets
        return self._scalar("H_ASSET", is_instant=True, prefer_bare=True)

    @property
    def total_assets_series(self) -> dict[str, float]:
        return self._series("H_ASSET", is_instant=True, prefer_bare=True)

    @property
    def total_assets_yoy(self) -> tuple[float, float] | None:
        return self._yoy("H_ASSET", is_instant=True, prefer_bare=True)

    @property
    def total_liabilities(self) -> float | None:
        bs = self._composer.compose_balance_sheet()
        if bs.total_liabilities is not None:
            return bs.total_liabilities
        return self._scalar("H_LIABILITY", is_instant=True, prefer_bare=True)

    @property
    def total_liabilities_series(self) -> dict[str, float]:
        return self._series("H_LIABILITY", is_instant=True, prefer_bare=True)

    @property
    def total_liabilities_yoy(self) -> tuple[float, float] | None:
        return self._yoy("H_LIABILITY", is_instant=True, prefer_bare=True)

    @property
    def total_equity(self) -> float | None:
        bs = self._composer.compose_balance_sheet()
        if bs.total_equity is not None:
            return bs.total_equity
        return self._scalar("H_EQUITY", is_instant=True) or self._scalar(
            "H_LIABILITY", {"M_EQUITY_TOTAL"}, is_instant=True
        )

    @property
    def total_equity_series(self) -> dict[str, float]:
        return self._series("H_EQUITY", is_instant=True) or self._series(
            "H_LIABILITY", {"M_EQUITY_TOTAL"}, is_instant=True
        )

    @property
    def total_equity_yoy(self) -> tuple[float, float] | None:
        return self._yoy("H_EQUITY", is_instant=True) or self._yoy(
            "H_LIABILITY", {"M_EQUITY_TOTAL"}, is_instant=True
        )

    @property
    def operating_cash_flow(self) -> float | None:
        cf = self._composer.compose_cash_flow()
        if cf.cfo is not None:
            return cf.cfo
        return self._scalar("H_CASH", {"M_OPERATING"})

    @property
    def operating_cash_flow_series(self) -> dict[str, float]:
        return self._series("H_CASH", {"M_OPERATING"})

    @property
    def operating_cash_flow_yoy(self) -> tuple[float, float] | None:
        return self._yoy("H_CASH", {"M_OPERATING"})

    @property
    def rpo(self) -> float | None:
        """Remaining performance obligations (contracted revenue backlog ASC 606)."""
        return self._scalar(
            "H_REVENUE", {"M_RPO_BACKLOG"}, is_instant=True
        ) or self._scalar("H_COMMITMENT", {"M_RPO_BACKLOG"}, is_instant=True)

    @property
    def rpo_series(self) -> dict[str, float]:
        return self._series(
            "H_REVENUE", {"M_RPO_BACKLOG"}, is_instant=True
        ) or self._series("H_COMMITMENT", {"M_RPO_BACKLOG"}, is_instant=True)

    @property
    def rpo_yoy(self) -> tuple[float, float] | None:
        return self._yoy("H_REVENUE", {"M_RPO_BACKLOG"}, is_instant=True) or self._yoy(
            "H_COMMITMENT", {"M_RPO_BACKLOG"}, is_instant=True
        )

    @property
    def capex(self) -> float | None:
        """Capital expenditures (payments to acquire PPE / productive assets)."""
        val = self._scalar("H_CASH", {"M_PPE_CAPEX"})
        return abs(val) if val is not None else None

    @property
    def capex_series(self) -> dict[str, float]:
        raw = self._series("H_CASH", {"M_PPE_CAPEX"})
        return {yr: abs(v) for yr, v in raw.items()}

    @property
    def free_cash_flow(self) -> float | None:
        """Free cash flow as the composed chain cfo - capex (Step 7 preset)."""
        if self._composition_resolver is not None:
            series = self.operating_cash_flow_series
            fiscal_year = int(max(series)) if series else None
            result = self._composition_resolver(
                (
                    ("+", "cfo"),
                    ("-", "capex"),
                ),
                fiscal_year,
            )
            return result.value
        return self._scalar("H_CASH", {"M_FREE_CASH_FLOW"})

    @property
    def uncommenced_leases(self) -> float | None:
        """Undiscounted uncommenced lease commitments off-balance sheet (ASC 842)."""
        return self._scalar(
            "H_COMMITMENT", {"M_UNCOMMENCED"}, is_instant=True
        ) or self._scalar("H_LIABILITY", {"M_UNCOMMENCED"}, is_instant=True)

    @property
    def derivatives(self) -> DerivativePortfolioView:
        """Dynamically resolve derivative exposures, risk categories, and netting."""
        graph = build_derivative_portfolio(
            self._facts, self._records, self._taxonomy, self._labels
        )
        return DerivativePortfolioView(graph)

    @property
    def debt(self) -> DebtStructureView:
        """Dynamically resolve capital structure, debt tranches, and maturities."""
        graph = build_debt_structure(
            self._facts, self._records, self._taxonomy, self._labels
        )
        return DebtStructureView(graph)

    @property
    def cash_rollforward(self) -> CashRollforwardView:
        """Dynamically resolve the ASU 2016-18 cash and restricted-cash rollforward."""
        graph = build_cash_rollforward(
            self._facts,
            self._records,
            self._taxonomy,
            self._labels,
            calculation_arcs=self._arcs,
        )
        return CashRollforwardView(graph)

    def level3_rollforward(
        self,
        axis_qname: str | None = None,
        member_qname: str | None = None,
        year: int | str | None = None,
    ) -> Level3RollforwardView:
        """Dynamically resolve one class's ASC 820 Level-3 rollforward."""
        graph = build_level3_rollforward(
            self._facts,
            self._records,
            self._taxonomy,
            self._labels,
            year,
            axis_qname=axis_qname,
            member_qname=member_qname,
        )
        return Level3RollforwardView(graph)

    def pension_funded_status(
        self,
        axis_qname: str | None = None,
        member_qname: str | None = None,
        year: int | str | None = None,
    ) -> PensionFundedStatusView:
        """Dynamically resolve one plan class's defined-benefit funded status."""
        graph = build_pension_funded_status(
            self._facts,
            self._records,
            self._taxonomy,
            self._labels,
            year,
            axis_qname=axis_qname,
            member_qname=member_qname,
        )
        return PensionFundedStatusView(graph)

    def equity_rollforward(
        self,
        member_qname: str | None = None,
        year: int | str | None = None,
    ) -> EquityRollforwardView:
        """Dynamically resolve the statement of changes in equity."""
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

    def segment_breakdown(
        self,
        concept_qname: str | None = None,
        axis_qname: str | None = None,
        year: int | str | None = None,
    ) -> SegmentBreakdownView:
        """Dynamically resolve one axis's members against the reported total."""
        graph = build_segment_breakdown(
            self._facts,
            self._records,
            self._taxonomy,
            self._labels,
            year,
            concept_qname=concept_qname,
            axis_qname=axis_qname,
            definition_arcs=self._definition_arcs,
        )
        return SegmentBreakdownView(graph)
