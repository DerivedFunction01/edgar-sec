"""Capex serving over the financials core.

The metric is the union of two coordinates of the same transaction:
the payments side and the purchase side, exclusion-guarded throughout.
"""

from __future__ import annotations

from edgar_sec.apps.client.financials_core import (
    _FALLBACK_LENGTH_CLASSES,
    FinancialsCore,
)


# Metric-definition exclusions at the scalar-selection seam: concepts
# whose modifier shape names a different measure than the metric.
CAPEX_EXCLUDED_MODS = frozenset({"M_SALE", "M_DISPOSAL"})
CAPEX_PURCHASE_MODS = frozenset({"M_PPE_CAPEX", "M_INVESTING"})
CAPEX_PURCHASE_ACT_MODS = frozenset({"M_PPE_CAPEX", "M_PURCHASE"})


class CapexServing(FinancialsCore):
    """Served capex machinery over the payments and purchase coordinates."""

    def _capex_series_at_class(self, length_class: str) -> dict[str, float]:
        """Capex magnitudes at one exact class over both coordinates.

        The payments coordinate governs any year it serves; the purchase
        coordinate fills the rest, classified shape before purchase-act.
        """
        cash = self._series_at_class(
            "H_CASH",
            {"M_PPE_CAPEX"},
            CAPEX_EXCLUDED_MODS,
            prefer_bare=True,
            length_class=length_class,
        )
        asset = self._series_at_class(
            "H_ASSET",
            CAPEX_PURCHASE_MODS,
            CAPEX_EXCLUDED_MODS,
            prefer_bare=True,
            length_class=length_class,
        )
        act = self._series_at_class(
            "H_ASSET",
            CAPEX_PURCHASE_ACT_MODS,
            CAPEX_EXCLUDED_MODS,
            prefer_bare=True,
            length_class=length_class,
        )
        merged = {yr: abs(v) for yr, v in act.items()}
        merged.update({yr: abs(v) for yr, v in asset.items()})
        merged.update({yr: abs(v) for yr, v in cash.items()})
        return merged

    def _capex_series_served(
        self, length_class: str = "ANNUAL"
    ) -> tuple[dict[str, float], str | None]:
        """Capex series plus its class, with the _series_served ladder."""
        series = self._capex_series_at_class(length_class)
        if series:
            return series, length_class
        if length_class != "ANNUAL":
            return {}, None
        for fallback in _FALLBACK_LENGTH_CLASSES:
            series = self._capex_series_at_class(fallback)
            if series:
                return series, fallback
        return {}, None

    def _capex_served(
        self,
        *,
        year: int | str | None = None,
        length_class: str = "ANNUAL",
    ) -> tuple[float | None, str | None]:
        """A capex scalar plus the length class of its served span."""
        series, cls = self._capex_series_served(length_class)
        if year:
            return series.get(str(year)), cls if str(year) in series else None
        if not series:
            return None, None
        return series[sorted(series)[-1]], cls

    def _capex_winners_at_class(self, length_class: str) -> dict[str, str]:
        """Winning capex concept per year of one class, union-governed.

        The same pools and overwrite order as _capex_series_at_class, so
        the winner named for a year is the concept that served its value.
        """
        cash = self._series_winners_at_class(
            "H_CASH",
            {"M_PPE_CAPEX"},
            CAPEX_EXCLUDED_MODS,
            prefer_bare=True,
            length_class=length_class,
        )
        asset = self._series_winners_at_class(
            "H_ASSET",
            CAPEX_PURCHASE_MODS,
            CAPEX_EXCLUDED_MODS,
            prefer_bare=True,
            length_class=length_class,
        )
        act = self._series_winners_at_class(
            "H_ASSET",
            CAPEX_PURCHASE_ACT_MODS,
            CAPEX_EXCLUDED_MODS,
            prefer_bare=True,
            length_class=length_class,
        )
        merged = dict(act)
        merged.update(asset)
        merged.update(cash)
        return merged
