"""Algebraic financial aggregates, multi-year YoY series, and projections."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from edgar_sec.apps.client.composition import ChainTerms, CompositionResult
from edgar_sec.apps.client.facts import DisplayRecord, build_display_records
from edgar_sec.apps.client.topics import (
    build_debt_structure,
    build_derivative_portfolio,
)
from edgar_sec.apps.client.views import DebtStructureView, DerivativePortfolioView
from edgar_sec.engine.xbrl.schema.models import CalculationArc, XbrlFact
from edgar_sec.engine.xbrl.solve.composer import StatementComposer
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy


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
    ) -> None:
        self._facts = tuple(facts)
        self._arcs = tuple(calculation_arcs)
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
    ) -> float | None:
        series = self._series(
            target_head,
            target_mods,
            excluded_mods,
            is_instant=is_instant,
            valence=valence,
            is_monetary=is_monetary,
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
    ) -> dict[str, float]:
        lex = self._taxonomy.token_lexicon
        if lex is None:
            return {}
        by_year: dict[str, list[float]] = {}
        for f in self._facts:
            if f.dimensions or not isinstance(f.value, (int, float)):
                continue
            if is_monetary and f.unit in ("pure", "shares", "item", "ratio"):
                continue
            record = self._records.get(f.concept_qname)
            if record is None:
                continue
            atom, val_type = record.atom, record.residuals
            if atom.head == target_head and target_mods.issubset(atom.modifiers):
                if excluded_mods and any(m in atom.modifiers for m in excluded_mods):
                    continue
                if valence and val_type != valence:
                    continue
                dt = f.instant_date if is_instant else f.end_date
                if not dt:
                    continue
                yr = dt[:4]
                if len(yr) == 4 and yr.isdigit():
                    by_year.setdefault(yr, []).append(float(f.value))

        return {yr: max(vals, key=abs) for yr, vals in by_year.items() if vals}

    def _yoy(
        self,
        target_head: str,
        target_mods: set[str] | frozenset[str] = frozenset(),
        excluded_mods: set[str] | frozenset[str] = frozenset(),
        *,
        is_instant: bool = False,
        valence: str | None = None,
    ) -> tuple[float, float] | None:
        series = self._series(
            target_head,
            target_mods,
            excluded_mods,
            is_instant=is_instant,
            valence=valence,
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
        return self._scalar("H_INCOME", {"M_NET_BOTTOMLINE"}) or self._scalar(
            "H_INCOME", {"V_NET"}
        )

    @property
    def net_income_series(self) -> dict[str, float]:
        return self._series("H_INCOME", {"M_NET_BOTTOMLINE"})

    @property
    def net_income_yoy(self) -> tuple[float, float] | None:
        return self._yoy("H_INCOME", {"M_NET_BOTTOMLINE"})

    @property
    def total_assets(self) -> float | None:
        bs = self._composer.compose_balance_sheet()
        if bs.total_assets is not None:
            return bs.total_assets
        return self._scalar("H_ASSET", is_instant=True)

    @property
    def total_assets_series(self) -> dict[str, float]:
        return self._series("H_ASSET", is_instant=True)

    @property
    def total_assets_yoy(self) -> tuple[float, float] | None:
        return self._yoy("H_ASSET", is_instant=True)

    @property
    def total_liabilities(self) -> float | None:
        bs = self._composer.compose_balance_sheet()
        if bs.total_liabilities is not None:
            return bs.total_liabilities
        return self._scalar("H_LIABILITY", is_instant=True)

    @property
    def total_liabilities_series(self) -> dict[str, float]:
        return self._series("H_LIABILITY", is_instant=True)

    @property
    def total_liabilities_yoy(self) -> tuple[float, float] | None:
        return self._yoy("H_LIABILITY", is_instant=True)

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
                    ("-", "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment"),
                ),
                fiscal_year,
            )
            return result.value
        cfo = self.operating_cash_flow
        cx = self.capex
        if cfo is not None and cx is not None:
            return cfo - cx
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
