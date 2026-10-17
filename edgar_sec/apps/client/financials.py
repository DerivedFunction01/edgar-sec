"""Algebraic financial aggregates, multi-year YoY series, and projections."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from edgar_sec.apps.client.views import DebtStructureView, DerivativePortfolioView
from edgar_sec.engine.xbrl.normalize.decomposer import decompose_concept
from edgar_sec.engine.xbrl.schema.models import CalculationArc, XbrlFact
from edgar_sec.engine.xbrl.solve.statement import (
    DebtStructureGraph,
    DerivativePortfolioGraph,
)
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy


class XbrlFinancials:
    """Algebraic financial aggregates, multi-year YoY series, and projections."""

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

    def _scalar(
        self,
        target_head: str,
        target_mods: set[str] | frozenset[str] = frozenset(),
        excluded_mods: set[str] | frozenset[str] = frozenset(),
        *,
        is_instant: bool = False,
        year: int | str | None = None,
    ) -> float | None:
        series = self._series(
            target_head, target_mods, excluded_mods, is_instant=is_instant
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
    ) -> dict[str, float]:
        lex = self._taxonomy.token_lexicon
        if lex is None:
            return {}
        by_year: dict[str, list[float]] = {}
        for f in self._facts:
            if f.dimensions or not isinstance(f.value, (int, float)):
                continue
            atom, _, _, _ = decompose_concept(f.concept_qname, lex)
            if atom.head == target_head and target_mods.issubset(atom.modifiers):
                if excluded_mods and any(m in atom.modifiers for m in excluded_mods):
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
    ) -> tuple[float, float] | None:
        series = self._series(
            target_head, target_mods, excluded_mods, is_instant=is_instant
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
        return self._scalar("H_REVENUE")

    @property
    def revenue_series(self) -> dict[str, float]:
        return self._series("H_REVENUE")

    @property
    def revenue_yoy(self) -> tuple[float, float] | None:
        return self._yoy("H_REVENUE")

    @property
    def gross_profit(self) -> float | None:
        return self._scalar("H_INCOME", {"M_GROSS"}) or self._scalar(
            "H_INCOME", {"M_GROSS_MARGIN"}
        )

    @property
    def gross_profit_series(self) -> dict[str, float]:
        return self._series("H_INCOME", {"M_GROSS"}) or self._series(
            "H_INCOME", {"M_GROSS_MARGIN"}
        )

    @property
    def gross_profit_yoy(self) -> tuple[float, float] | None:
        return self._yoy("H_INCOME", {"M_GROSS"}) or self._yoy(
            "H_INCOME", {"M_GROSS_MARGIN"}
        )

    @property
    def operating_income(self) -> float | None:
        return self._scalar("H_INCOME", {"M_OPERATING"})

    @property
    def operating_income_series(self) -> dict[str, float]:
        return self._series("H_INCOME", {"M_OPERATING"})

    @property
    def operating_income_yoy(self) -> tuple[float, float] | None:
        return self._yoy("H_INCOME", {"M_OPERATING"})

    @property
    def net_income(self) -> float | None:
        return self._scalar("H_INCOME", {"M_NET_BOTTOMLINE"})

    @property
    def net_income_series(self) -> dict[str, float]:
        return self._series("H_INCOME", {"M_NET_BOTTOMLINE"})

    @property
    def net_income_yoy(self) -> tuple[float, float] | None:
        return self._yoy("H_INCOME", {"M_NET_BOTTOMLINE"})

    @property
    def total_assets(self) -> float | None:
        return self._scalar("H_ASSET", is_instant=True)

    @property
    def total_assets_series(self) -> dict[str, float]:
        return self._series("H_ASSET", is_instant=True)

    @property
    def total_assets_yoy(self) -> tuple[float, float] | None:
        return self._yoy("H_ASSET", is_instant=True)

    @property
    def total_liabilities(self) -> float | None:
        return self._scalar("H_LIABILITY", is_instant=True)

    @property
    def total_liabilities_series(self) -> dict[str, float]:
        return self._series("H_LIABILITY", is_instant=True)

    @property
    def total_liabilities_yoy(self) -> tuple[float, float] | None:
        return self._yoy("H_LIABILITY", is_instant=True)

    @property
    def total_equity(self) -> float | None:
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
        return self._scalar("H_CASH", {"M_OPERATING"})

    @property
    def operating_cash_flow_series(self) -> dict[str, float]:
        return self._series("H_CASH", {"M_OPERATING"})

    @property
    def operating_cash_flow_yoy(self) -> tuple[float, float] | None:
        return self._yoy("H_CASH", {"M_OPERATING"})

    @property
    def derivatives(self) -> DerivativePortfolioView:
        """Dynamically resolve derivative exposures and netted commitments."""
        gross_assets = self._scalar("H_ASSET", {"M_DERIVATIVE"}, is_instant=True)
        net_assets = self._scalar("H_ASSET", {"M_DERIVATIVE", "V_NET"}, is_instant=True)
        gross_liab = self._scalar("H_LIABILITY", {"M_DERIVATIVE"}, is_instant=True)
        net_liab = self._scalar(
            "H_LIABILITY", {"M_DERIVATIVE", "V_NET"}, is_instant=True
        )
        notional = self._scalar("H_NOTIONAL", is_instant=True)
        collateral = self._scalar(
            "H_ASSET", {"M_CASH_COLLATERAL_OFFSET"}, is_instant=True
        )
        master_netting = self._scalar(
            "H_ASSET", {"M_NOT_SUBJECT_TO_NETTING"}, is_instant=True
        )
        graph = DerivativePortfolioGraph(
            gross_assets=gross_assets,
            net_assets=net_assets,
            gross_liabilities=gross_liab,
            net_liabilities=net_liab,
            notional_amount=notional,
            collateral_offsets=collateral,
            master_netting_offsets=master_netting,
            positions=(),
        )
        return DerivativePortfolioView(graph)

    @property
    def debt(self) -> DebtStructureView:
        """Dynamically resolve capital structure, debt tranches, and leases."""
        total_debt = self._scalar("H_LIABILITY", {"M_DEBT"}, is_instant=True)
        current_debt = self._scalar(
            "H_LIABILITY", {"M_DEBT", "M_CURRENT"}, is_instant=True
        )
        lt_debt = self._scalar(
            "H_LIABILITY", {"M_DEBT", "M_NONCURRENT"}, is_instant=True
        )
        leases = self._scalar(
            "H_LIABILITY", {"M_LEASE"}, is_instant=True
        ) or self._scalar("H_LIABILITY", {"M_ROU_LEASE"}, is_instant=True)
        graph = DebtStructureGraph(
            total_debt=total_debt,
            current_debt=current_debt,
            long_term_debt=lt_debt,
            leases=leases,
            positions=(),
        )
        return DebtStructureView(graph)
