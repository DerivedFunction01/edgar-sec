"""Exact-class series for the named catalogue metrics.

Each branch mirrors its default served series through exact-class
access; instant metrics serve under any class name.
"""

from __future__ import annotations

from edgar_sec.apps.client.financials.financials_series import (
    OCF_EXCLUDED_MODS,
    REVENUE_EXCLUDED_MODS,
)


class ClassedSeriesMixin:
    """Named-metric series at one exact length class."""

    def _classed_series(self, metric: str, length_class: str) -> dict[str, float]:
        """One series metric at one exact length class; no fallback ladder.

        Each branch mirrors its default served series through exact-class
        access; instant metrics serve under any class name.
        """
        at = self._series_at_class
        if metric == "revenue":
            return at(
                "H_REVENUE",
                excluded_mods=REVENUE_EXCLUDED_MODS,
                length_class=length_class,
            )
        if metric == "gross_profit":
            return (
                at("H_INCOME", {"M_GROSS"}, length_class=length_class)
                or at("H_INCOME", {"M_GROSS_MARGIN"}, length_class=length_class)
                or at("H_INCOME", valence="V_GROSS", length_class=length_class)
            )
        if metric == "operating_income":
            return at("H_INCOME", {"M_OPERATING"}, length_class=length_class)
        if metric == "net_income":
            root = self._kernel.compose_income_statement().root_qname
            rooted = self._concept_series_at_class(root, length_class) if root else {}
            return (
                rooted
                or at(
                    "H_INCOME",
                    {"M_NET_BOTTOMLINE"},
                    {"M_NONCONTROLLING_INTEREST", "M_COMMON", "V_BASIC", "V_DILUTED"},
                    length_class=length_class,
                )
                or at("H_INCOME", {"M_NET_BOTTOMLINE"}, length_class=length_class)
            )
        if metric == "total_assets":
            return at(
                "H_ASSET",
                is_instant=True,
                prefer_bare=True,
                length_class=length_class,
            )
        if metric == "total_liabilities":
            return at(
                "H_LIABILITY",
                is_instant=True,
                prefer_bare=True,
                length_class=length_class,
            )
        if metric == "total_equity":
            return at("H_EQUITY", is_instant=True, length_class=length_class) or at(
                "H_LIABILITY",
                {"M_EQUITY_TOTAL"},
                is_instant=True,
                length_class=length_class,
            )
        if metric == "operating_cash_flow":
            return at(
                "H_CASH",
                {"M_OPERATING"},
                OCF_EXCLUDED_MODS,
                length_class=length_class,
            )
        if metric == "rpo":
            return at(
                "H_REVENUE",
                {"M_RPO_BACKLOG"},
                is_instant=True,
                length_class=length_class,
            ) or at(
                "H_COMMITMENT",
                {"M_RPO_BACKLOG"},
                is_instant=True,
                length_class=length_class,
            )
        if metric == "capex":
            return self._capex_series_at_class(length_class)
        if metric in ("eps_basic", "eps_diluted"):
            mapping = self._eps_served_map(diluted=metric == "eps_diluted")
            return {
                yr: value
                for (cls, yr), (value, _provenance) in sorted(mapping.items())
                if cls == length_class
            }
        if metric in ("weighted_shares_basic", "weighted_shares_diluted"):
            mapping = self._shares_served_map(
                diluted=metric == "weighted_shares_diluted"
            )
            return {
                yr: value
                for (cls, yr), value in sorted(mapping.items())
                if cls == length_class
            }
        raise ValueError(f"metric {metric!r} has no classed series")
