"""Algebraic financial aggregates, multi-year YoY series, and projections."""

from __future__ import annotations

from collections.abc import Callable

from edgar_sec.apps.client.catalog import build_catalog
from edgar_sec.apps.client.comparison import DERIVED_MARGINS
from edgar_sec.apps.client.financials_core import (
    OCF_EXCLUDED_MODS,
    REVENUE_EXCLUDED_MODS,
)
from edgar_sec.apps.client.fiscal import (
    chain_span_class,
    filed_length_class,
    graph_span_class,
    node_length_class,
    transition_length_class,
)
from edgar_sec.apps.client.financials_ttm import TtmServing
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
    "eps_basic": "eps_basic_series",
    "eps_diluted": "eps_diluted_series",
    "weighted_shares_basic": "weighted_shares_basic_series",
    "weighted_shares_diluted": "weighted_shares_diluted_series",
}
_SCALAR_ONLY_METRICS = ("free_cash_flow", "uncommenced_leases")


class XbrlFinancials(TtmServing):
    """Algebraic financial aggregates, multi-year YoY series, and projections."""

    @property
    def revenue(self) -> float | None:
        inc = self._kernel.compose_income_statement()
        if inc.gross_profit_graph and inc.gross_profit_graph.root:
            for child in inc.gross_profit_graph.children(
                inc.gross_profit_graph.root.concept_qname
            ):
                if child.atom.head == "H_REVENUE" and child.value is not None:
                    return child.value
        return self._scalar("H_REVENUE", excluded_mods=REVENUE_EXCLUDED_MODS)

    @property
    def revenue_series(self) -> dict[str, float]:
        return self._series("H_REVENUE", excluded_mods=REVENUE_EXCLUDED_MODS)

    @property
    def revenue_yoy(self) -> tuple[float, float] | None:
        return self._yoy("H_REVENUE", excluded_mods=REVENUE_EXCLUDED_MODS)

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
        return self._operating_cash_flow_served()[0]

    @property
    def operating_cash_flow_series(self) -> dict[str, float]:
        return self._series("H_CASH", {"M_OPERATING"}, OCF_EXCLUDED_MODS)

    @property
    def operating_cash_flow_yoy(self) -> tuple[float, float] | None:
        return self._yoy("H_CASH", {"M_OPERATING"}, OCF_EXCLUDED_MODS)

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
        return self._capex_served()[0]

    @property
    def capex_series(self) -> dict[str, float]:
        return self._capex_series_served()[0]

    @property
    def free_cash_flow(self) -> float | None:
        """Free cash flow as the composed chain cfo - capex (Step 7 preset)."""
        return self._free_cash_flow_served()[0]

    @property
    def uncommenced_leases(self) -> float | None:
        """Undiscounted uncommenced lease commitments off-balance sheet (ASC 842)."""
        return self._scalar(
            "H_COMMITMENT", {"M_UNCOMMENCED"}, is_instant=True
        ) or self._scalar("H_LIABILITY", {"M_UNCOMMENCED"}, is_instant=True)

    @property
    def eps_basic(self) -> float | None:
        """Earnings per share, basic: filed, else derived by the EPS identity."""
        return self._eps_basic_served()[0]

    def _eps_basic_served(self) -> tuple[float | None, str | None]:
        """Basic EPS plus provenance: filed, or the identity it derived from."""
        value, provenance, _cls = self._eps_scalar_served(diluted=False)
        return value, provenance

    @property
    def eps_basic_series(self) -> dict[str, float]:
        return self._eps_series(diluted=False)

    @property
    def eps_basic_yoy(self) -> tuple[float, float] | None:
        return self._eps_yoy(diluted=False)

    @property
    def eps_diluted(self) -> float | None:
        """Earnings per share, diluted: filed, else derived by the EPS identity."""
        return self._eps_diluted_served()[0]

    def _eps_diluted_served(self) -> tuple[float | None, str | None]:
        """Diluted EPS plus provenance: filed, or the identity it derived from."""
        value, provenance, _cls = self._eps_scalar_served(diluted=True)
        return value, provenance

    @property
    def eps_diluted_series(self) -> dict[str, float]:
        return self._eps_series(diluted=True)

    @property
    def eps_diluted_yoy(self) -> tuple[float, float] | None:
        return self._eps_yoy(diluted=True)

    @property
    def weighted_shares_basic(self) -> float | None:
        """Weighted-average shares outstanding, basic, as filed."""
        return self._weighted_shares_basic_served()[0]

    def _weighted_shares_basic_served(self) -> tuple[float | None, str | None]:
        """Basic weighted shares plus the length class they served from."""
        return self._shares_scalar_served(diluted=False)

    @property
    def weighted_shares_basic_series(self) -> dict[str, float]:
        return self._shares_series(diluted=False)

    @property
    def weighted_shares_basic_yoy(self) -> tuple[float, float] | None:
        return self._shares_yoy(diluted=False)

    @property
    def weighted_shares_diluted(self) -> float | None:
        """Weighted-average shares outstanding, diluted, as filed."""
        return self._weighted_shares_diluted_served()[0]

    def _weighted_shares_diluted_served(self) -> tuple[float | None, str | None]:
        """Diluted weighted shares plus the length class they served from."""
        return self._shares_scalar_served(diluted=True)

    @property
    def weighted_shares_diluted_series(self) -> dict[str, float]:
        return self._shares_series(diluted=True)

    @property
    def weighted_shares_diluted_yoy(self) -> tuple[float, float] | None:
        return self._shares_yoy(diluted=True)

    def provenance(self, metric: str) -> str | None:
        """How a per-share metric's scalar was served: filed or derived.

        Only the per-share catalogue carries derivation provenance; a
        derived value names the identity and both of its filed legs.
        """
        if metric == "eps_basic":
            return self._eps_basic_served()[1]
        if metric == "eps_diluted":
            return self._eps_diluted_served()[1]
        if metric in ("weighted_shares_basic", "weighted_shares_diluted"):
            return "filed" if getattr(self, metric) is not None else None
        known = [
            "eps_basic",
            "eps_diluted",
            "weighted_shares_basic",
            "weighted_shares_diluted",
        ]
        raise ValueError(
            f"provenance is not tracked for metric {metric!r}; expected one of {known}"
        )

    def series(
        self, metric: str, *, length_class: str | None = None
    ) -> dict[str, float]:
        """A served metric's series, at one exact length class when named.

        A named class serves exactly that class with no fallback ladder;
        an unserved class is an empty series, never another class's data.
        """
        if length_class is None:
            series_attr = _SERIES_ATTRIBUTES.get(metric)
            if series_attr is not None:
                return getattr(self, series_attr)
            known = sorted(_SERIES_ATTRIBUTES) + sorted(_SCALAR_ONLY_METRICS)
            if metric in _SCALAR_ONLY_METRICS:
                raise ValueError(f"metric {metric!r} has no series; use value()")
            raise ValueError(f"unknown metric {metric!r}; expected one of {known}")
        if metric in _SERIES_ATTRIBUTES:
            return self._classed_series(metric, length_class)
        known = sorted(_SERIES_ATTRIBUTES) + sorted(_SCALAR_ONLY_METRICS)
        if metric in _SCALAR_ONLY_METRICS:
            raise ValueError(f"metric {metric!r} has no series; use value()")
        raise ValueError(f"unknown metric {metric!r}; expected one of {known}")

    def value(
        self,
        metric: str,
        *,
        period_offset: int = 0,
        length_class: str | None = None,
    ) -> float | None:
        """A served metric's value, period_offset periods before its latest.

        Reads only already-served series (or the scalar at offset 0);
        a named length class reads that class's series exactly.
        """
        if period_offset < 0:
            raise ValueError(f"period_offset must be >= 0, got {period_offset}")
        if length_class is not None:
            if metric == "free_cash_flow":
                if period_offset > 0:
                    return None
                return self._free_cash_flow_served(length_class)[0]
            if metric in _SCALAR_ONLY_METRICS:
                if period_offset > 0 or length_class != "INSTANT":
                    return None
                return getattr(self, metric)
            series = self.series(metric, length_class=length_class)
            years = sorted(series, reverse=True)
            if period_offset >= len(years):
                return None
            return series[years[period_offset]]
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

    def filed_length_class(self) -> str | None:
        """The length class this filing's dei focus derivation names."""
        return filed_length_class(self._kernel.facts, self._kernel.filed_metadata)

    def transition_length_class(self) -> str | None:
        """A transition filing's stub length class; None for other filings."""
        return transition_length_class(self._kernel.facts, self._kernel.filed_metadata)

    def span_class(self, metric: str, *, length_class: str | None = None) -> str | None:
        """Length class of the span a metric's latest value was served from.

        The class names scalar and series alike; a named class answers
        whether that class serves at all. None when unserved.
        """
        if length_class is not None:
            if metric == "free_cash_flow":
                return self._free_cash_flow_served(length_class)[1]
            if metric in _SCALAR_ONLY_METRICS:
                if length_class == "INSTANT" and getattr(self, metric) is not None:
                    return "INSTANT"
                return None
            if metric in _SERIES_ATTRIBUTES:
                return (
                    length_class
                    if self.series(metric, length_class=length_class)
                    else None
                )
            known = sorted(_SERIES_ATTRIBUTES) + sorted(_SCALAR_ONLY_METRICS)
            raise ValueError(f"unknown metric {metric!r}; expected one of {known}")
        if metric == "revenue":
            inc = self._kernel.compose_income_statement()
            graph = inc.gross_profit_graph
            if graph is not None and graph.root is not None:
                for child in graph.children(graph.root.concept_qname):
                    if child.atom.head == "H_REVENUE" and child.value is not None:
                        return node_length_class(child)
            return self._scalar_served(
                "H_REVENUE", excluded_mods=REVENUE_EXCLUDED_MODS
            )[1]
        if metric == "gross_profit":
            inc = self._kernel.compose_income_statement()
            if inc.gross_profit is not None:
                return graph_span_class(inc.gross_profit_graph)
            return chain_span_class(
                self._scalar_served("H_INCOME", {"M_GROSS"}),
                self._scalar_served("H_INCOME", {"M_GROSS_MARGIN"}),
                self._scalar_served("H_INCOME", valence="V_GROSS"),
            )
        if metric == "operating_income":
            inc = self._kernel.compose_income_statement()
            if inc.operating_income is not None:
                return graph_span_class(inc.operating_income_graph)
            return self._scalar_served("H_INCOME", {"M_OPERATING"})[1]
        if metric == "net_income":
            inc = self._kernel.compose_income_statement()
            if inc.net_income is not None and inc.root is not None:
                return node_length_class(inc.root)
            return chain_span_class(
                self._scalar_served(
                    "H_INCOME",
                    {"M_NET_BOTTOMLINE"},
                    {"M_NONCONTROLLING_INTEREST", "M_COMMON", "V_BASIC", "V_DILUTED"},
                ),
                self._scalar_served("H_INCOME", {"V_NET"}),
            )
        if metric == "total_assets":
            bs = self._kernel.compose_balance_sheet()
            if bs.total_assets is not None:
                return graph_span_class(bs.assets_graph)
            return self._scalar_served("H_ASSET", is_instant=True, prefer_bare=True)[1]
        if metric == "total_liabilities":
            bs = self._kernel.compose_balance_sheet()
            if bs.total_liabilities is not None:
                return graph_span_class(bs.liabilities_graph)
            return self._scalar_served(
                "H_LIABILITY", is_instant=True, prefer_bare=True
            )[1]
        if metric == "total_equity":
            bs = self._kernel.compose_balance_sheet()
            if bs.total_equity is not None:
                return graph_span_class(bs.equity_graph)
            return chain_span_class(
                self._scalar_served("H_EQUITY", is_instant=True),
                self._scalar_served("H_LIABILITY", {"M_EQUITY_TOTAL"}, is_instant=True),
            )
        if metric == "operating_cash_flow":
            return self._operating_cash_flow_served()[1]
        if metric == "rpo":
            return chain_span_class(
                self._scalar_served("H_REVENUE", {"M_RPO_BACKLOG"}, is_instant=True),
                self._scalar_served("H_COMMITMENT", {"M_RPO_BACKLOG"}, is_instant=True),
            )
        if metric == "capex":
            return self._capex_served()[1]
        if metric == "free_cash_flow":
            return self._free_cash_flow_served()[1]
        if metric == "uncommenced_leases":
            return chain_span_class(
                self._scalar_served("H_COMMITMENT", {"M_UNCOMMENCED"}, is_instant=True),
                self._scalar_served("H_LIABILITY", {"M_UNCOMMENCED"}, is_instant=True),
            )
        if metric == "eps_basic":
            return self._eps_scalar_served(diluted=False)[2]
        if metric == "eps_diluted":
            return self._eps_scalar_served(diluted=True)[2]
        if metric == "weighted_shares_basic":
            return self._weighted_shares_basic_served()[1]
        if metric == "weighted_shares_diluted":
            return self._weighted_shares_diluted_served()[1]
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
                catalog_entries=self._kernel.graph_once(
                    ("catalog_entries",), lambda: build_catalog(self._kernel)
                ),
            ),
        )
        return SegmentBreakdownView(graph)
