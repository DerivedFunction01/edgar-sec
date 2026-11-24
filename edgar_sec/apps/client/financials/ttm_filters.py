"""Metric vocabulary for TTM derivation: the span classes, the atom
filters per flow metric, and the metric classes treated specially.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.apps.client.financials.financials_capex import (
    CAPEX_EXCLUDED_MODS,
    CAPEX_PURCHASE_ACT_MODS,
    CAPEX_PURCHASE_MODS,
)
from edgar_sec.apps.client.financials.financials_core import (
    OCF_EXCLUDED_MODS,
    REVENUE_EXCLUDED_MODS,
)


_TTM_CLASSES = ("QUARTER", "YTD_2Q", "YTD_3Q", "ANNUAL")


@dataclass(frozen=True)
class _AtomFilter:
    head: str
    mods: frozenset[str] = frozenset()
    excluded: frozenset[str] = frozenset()
    valence: str | None = None
    prefer_bare: bool = False
    concept: str | None = None
    absolute: bool = False


_FLOW_GROUPS: dict[str, tuple[tuple[_AtomFilter, ...], ...]] = {
    "revenue": ((_AtomFilter("H_REVENUE", excluded=REVENUE_EXCLUDED_MODS),),),
    "gross_profit": (
        (_AtomFilter("H_INCOME", mods=frozenset({"M_GROSS"})),),
        (_AtomFilter("H_INCOME", mods=frozenset({"M_GROSS_MARGIN"})),),
        (_AtomFilter("H_INCOME", valence="V_GROSS"),),
    ),
    "operating_income": ((_AtomFilter("H_INCOME", mods=frozenset({"M_OPERATING"})),),),
    "net_income": (
        (
            _AtomFilter(
                "H_INCOME",
                mods=frozenset({"M_NET_BOTTOMLINE"}),
                excluded=frozenset(
                    {
                        "M_NONCONTROLLING_INTEREST",
                        "M_COMMON",
                        "V_BASIC",
                        "V_DILUTED",
                    }
                ),
            ),
        ),
        (_AtomFilter("H_INCOME", mods=frozenset({"M_NET_BOTTOMLINE"})),),
    ),
    "operating_cash_flow": (
        (
            _AtomFilter(
                "H_CASH",
                mods=frozenset({"M_OPERATING"}),
                excluded=OCF_EXCLUDED_MODS,
            ),
        ),
    ),
    "capex": (
        (
            _AtomFilter(
                "H_ASSET",
                mods=CAPEX_PURCHASE_ACT_MODS,
                excluded=CAPEX_EXCLUDED_MODS,
                prefer_bare=True,
                absolute=True,
            ),
            _AtomFilter(
                "H_ASSET",
                mods=CAPEX_PURCHASE_MODS,
                excluded=CAPEX_EXCLUDED_MODS,
                prefer_bare=True,
                absolute=True,
            ),
            _AtomFilter(
                "H_CASH",
                mods=frozenset({"M_PPE_CAPEX"}),
                excluded=CAPEX_EXCLUDED_MODS,
                prefer_bare=True,
                absolute=True,
            ),
        ),
    ),
}

_INSTANT_METRICS = ("total_assets", "total_liabilities", "total_equity", "rpo")

_SHARE_METRICS = {
    "weighted_shares_basic": False,
    "weighted_shares_diluted": True,
}

_EPS_METRICS = ("eps_basic", "eps_diluted")
