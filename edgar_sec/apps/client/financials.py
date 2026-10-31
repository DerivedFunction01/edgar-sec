"""Algebraic financial aggregates, multi-year YoY series, and projections."""

from __future__ import annotations

from collections.abc import Callable

from edgar_sec.apps.client.comparison import DERIVED_MARGINS
from edgar_sec.apps.client.composition import ChainTerms, CompositionResult
from edgar_sec.apps.client.kernel import FilingKernel
from edgar_sec.apps.client.rollforwards import (
    build_fair_value_hierarchy,
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
    FairValueHierarchyView,
    Level3RollforwardView,
    PensionFundedStatusView,
    SegmentBreakdownView,
)


_SERIES_ATTRIBUTES: dict[str, str] = {
    "revenue": "revenue_series",
    "gross_profit": "gross_profit_series",
    "operating_income": "operating_income_series",
    "net_income": "net_income_series",
    "total_assets": "total_assets_series",
    "total_liabilities": "total_liabilities_series",
    "total_equity": "total_equity_series",
    "operating_cash_flow": "operating_cash_flow_series",
    "rpo": "rpo_series",
    "capex": "capex_series",
}
_SCALAR_ONLY_METRICS = ("free_cash_flow", "uncommenced_leases")


class XbrlFinancials:
    """Algebraic financial aggregates, multi-year YoY series, and projections."""

    def __init__(
        self,
        kernel: FilingKernel,
        *,
        composition_resolver: Callable[[ChainTerms, int | None], CompositionResult]
        | None = None,
    ) -> None:
        self._kernel = kernel
        self._facts = kernel.facts
        self._arcs = kernel.calculation_arcs
        self._definition_arcs = kernel.definition_arcs
        self._taxonomy = kernel.taxonomy
        self._labels = kernel.labels
        self._records = kernel.records
        self._composition_resolver = composition_resolver
        self._composer = kernel.composer

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
        key = (
            "series",
            target_head,
            frozenset(target_mods),
            frozenset(excluded_mods),
            is_instant,
            valence,
            is_monetary,
            prefer_bare,
            length_class,
        )
        computed = self._kernel.series(
            key,
            lambda: self._compute_series(
                target_head,
                target_mods,
                excluded_mods,
                is_instant=is_instant,
                valence=valence,
                is_monetary=is_monetary,
                prefer_bare=prefer_bare,
                length_class=length_class,
            ),
        )
        return dict(computed)

    def _compute_series(
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
        best = self._kernel.best_ranked(
            instant=is_instant,
            length_class=length_class,
            monetary_only=is_monetary,
        )
        by_year: dict[str, tuple[int, float, float]] = {}
        for (qname, yr), (_rank, val) in best.items():
            if len(yr) != 4 or not yr.isdigit():
                continue
            record = self._records.get(qname)
            if record is None:
                continue
            atom = record.atom
            if atom.head != target_head or not target_mods.issubset(atom.modifiers):
                continue
            if excluded_mods and any(m in atom.modifiers for m in excluded_mods):
                continue
            if valence and valence not in atom.modifiers:
                continue
            cand = (len(atom.modifiers), -abs(val), val)
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
        inc = self._kernel.compose_income_statement()
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
        inc = self._kernel.compose_income_statement()
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
        inc = self._kernel.compose_income_statement()
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
        inc = self._kernel.compose_income_statement()
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
        computed = self._kernel.series(
            ("concept_series", qname, length_class),
            lambda: self._compute_concept_series(qname, length_class),
        )
        return dict(computed)

    def _compute_concept_series(
        self, qname: str, length_class: str
    ) -> dict[str, float]:
        best = self._kernel.best_ranked(
            instant=None, length_class=length_class, monetary_only=True
        )
        return {
            yr: val for (concept, yr), (_rank, val) in best.items() if concept == qname
        }

    @property
    def net_income_series(self) -> dict[str, float]:
        root = self._kernel.compose_income_statement().root_qname
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
        bs = self._kernel.compose_balance_sheet()
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
        bs = self._kernel.compose_balance_sheet()
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
        bs = self._kernel.compose_balance_sheet()
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
        cf = self._kernel.compose_cash_flow()
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

    def value(self, metric: str, *, period_offset: int = 0) -> float | None:
        """A served metric's value, period_offset periods before its latest.

        Reads only the metric's already-served series (or, for metrics
        with no series, its scalar at offset 0); nothing is re-derived.
        """
        if period_offset < 0:
            raise ValueError(f"period_offset must be >= 0, got {period_offset}")
        series_attr = _SERIES_ATTRIBUTES.get(metric)
        if series_attr is not None:
            series = getattr(self, series_attr)
            years = sorted(series, reverse=True)
            if period_offset >= len(years):
                return None
            return series[years[period_offset]]
        if metric in _SCALAR_ONLY_METRICS:
            return getattr(self, metric) if period_offset == 0 else None
        known = sorted(_SERIES_ATTRIBUTES) + sorted(_SCALAR_ONLY_METRICS)
        raise ValueError(f"unknown metric {metric!r}; expected one of {known}")

    def metrics(self) -> dict[str, float]:
        """Derived ratios declared in comparison.DERIVED_MARGINS, from served scalars.

        A ratio whose numerator or denominator is unserved (or whose
        denominator is zero) is absent, matching compare_companies.
        """
        out: dict[str, float] = {}
        for key, _label, numerator, denominator in DERIVED_MARGINS:
            num = getattr(self, numerator)
            den = getattr(self, denominator)
            if num is not None and den:
                out[key] = num / den
        return out

    @property
    def derivatives(self) -> DerivativePortfolioView:
        """Dynamically resolve derivative exposures, risk categories, and netting."""
        graph = self._kernel.graph_once(
            ("derivatives",),
            lambda: build_derivative_portfolio(
                self._facts, self._records, self._taxonomy, self._labels
            ),
        )
        return DerivativePortfolioView(graph)

    @property
    def debt(self) -> DebtStructureView:
        """Dynamically resolve capital structure, debt tranches, and maturities."""
        graph = self._kernel.graph_once(
            ("debt",),
            lambda: build_debt_structure(
                self._facts, self._records, self._taxonomy, self._labels
            ),
        )
        return DebtStructureView(graph)

    @property
    def cash_rollforward(self) -> CashRollforwardView:
        """Dynamically resolve the ASU 2016-18 cash and restricted-cash rollforward."""
        graph = self._kernel.graph_once(
            ("cash_rollforward",),
            lambda: build_cash_rollforward(
                self._facts,
                self._records,
                self._taxonomy,
                self._labels,
                calculation_arcs=self._arcs,
            ),
        )
        return CashRollforwardView(graph)

    def fair_value_hierarchy(
        self,
        year: int | str | None = None,
    ) -> FairValueHierarchyView:
        """Dynamically resolve each concept's fair-value level split."""
        graph = self._kernel.graph_once(
            ("fair_value_hierarchy", year),
            lambda: build_fair_value_hierarchy(
                self._facts,
                self._records,
                self._taxonomy,
                self._labels,
                year,
            ),
        )
        return FairValueHierarchyView(graph)

    def level3_rollforward(
        self,
        axis_qname: str | None = None,
        member_qname: str | None = None,
        year: int | str | None = None,
    ) -> Level3RollforwardView:
        """Dynamically resolve one class's ASC 820 Level-3 rollforward."""
        graph = self._kernel.graph_once(
            ("level3_rollforward", axis_qname, member_qname, year),
            lambda: build_level3_rollforward(
                self._facts,
                self._records,
                self._taxonomy,
                self._labels,
                year,
                axis_qname=axis_qname,
                member_qname=member_qname,
            ),
        )
        return Level3RollforwardView(graph)

    def pension_funded_status(
        self,
        axis_qname: str | None = None,
        member_qname: str | None = None,
        year: int | str | None = None,
    ) -> PensionFundedStatusView:
        """Dynamically resolve one plan class's defined-benefit funded status."""
        graph = self._kernel.graph_once(
            ("pension_funded_status", axis_qname, member_qname, year),
            lambda: build_pension_funded_status(
                self._facts,
                self._records,
                self._taxonomy,
                self._labels,
                year,
                axis_qname=axis_qname,
                member_qname=member_qname,
            ),
        )
        return PensionFundedStatusView(graph)

    def equity_rollforward(
        self,
        member_qname: str | None = None,
        year: int | str | None = None,
    ) -> EquityRollforwardView:
        """Dynamically resolve the statement of changes in equity."""
        return self._kernel.equity_rollforward(member_qname=member_qname, year=year)

    def segment_breakdown(
        self,
        concept_qname: str | None = None,
        axis_qname: str | None = None,
        year: int | str | None = None,
    ) -> SegmentBreakdownView:
        """Dynamically resolve one axis's members against the reported total."""
        graph = self._kernel.graph_once(
            ("segment_breakdown", concept_qname, axis_qname, year),
            lambda: build_segment_breakdown(
                self._facts,
                self._records,
                self._taxonomy,
                self._labels,
                year,
                concept_qname=concept_qname,
                axis_qname=axis_qname,
                definition_arcs=self._definition_arcs,
            ),
        )
        return SegmentBreakdownView(graph)
