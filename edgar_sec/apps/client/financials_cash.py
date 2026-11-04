"""Cash-flow metric serving over the financials core.

Operating cash flow and free cash flow: served operands first, then
the composition chain and the span fallbacks, chain-guarded throughout.
"""

from __future__ import annotations

from edgar_sec.apps.client.composition import ChainTerms, CompositionResult
from edgar_sec.apps.client.financials_capex import CAPEX_EXCLUDED_MODS, CapexServing
from edgar_sec.apps.client.financials_core import OCF_EXCLUDED_MODS
from edgar_sec.apps.client.fiscal import composition_span_class, node_length_class
from edgar_sec.engine.xbrl.solve.antichain import AntiChainValidator


_FCF_CHAIN: ChainTerms = (("+", "cfo"), ("-", "capex"))


class CashFlowServing(CapexServing):
    """Served operating-cash-flow and free-cash-flow machinery."""

    def _operating_cash_flow_served(
        self,
    ) -> tuple[float | None, str | None, str | None]:
        """Operating cash flow, its span class, and the year it served at."""
        cf = self._kernel.compose_cash_flow()
        if cf.cfo is not None:
            root = cf.operating.root if cf.operating is not None else None
            cls = node_length_class(root) if root is not None else None
            year = max(root.values) if root is not None and root.values else None
            return cf.cfo, cls, year
        series, cls = self._series_served("H_CASH", {"M_OPERATING"}, OCF_EXCLUDED_MODS)
        if not series:
            return None, None, None
        year = max(series)
        return series[year], cls, year

    def _free_cash_flow_served(
        self, length_class: str | None = None
    ) -> tuple[float | None, str | None]:
        """Free cash flow plus the length class it was served from.

        The served operands' own difference answers first, at the operating
        leg's served class and year; the chain and fallbacks follow.
        """
        if length_class is not None:
            return self._classed_cash_difference(length_class)
        ocf, ocf_class, ocf_year = self._operating_cash_flow_served()
        if ocf is not None and ocf_class is not None and ocf_year is not None:
            capex, capex_class = self._capex_served(
                year=ocf_year, length_class=ocf_class
            )
            if capex is not None and capex_class == ocf_class:
                return ocf - abs(capex), ocf_class
        if self._composition_resolver is not None:
            series = self._series("H_CASH", {"M_OPERATING"}, OCF_EXCLUDED_MODS)
            fiscal_year = int(max(series)) if series else None
            result = self._composition_resolver(_FCF_CHAIN, fiscal_year)
            if result.value is not None and not self._chain_leg_refused(result):
                return result.value, composition_span_class(result)
        else:
            value, cls = self._scalar_served("H_CASH", {"M_FREE_CASH_FLOW"})
            if value is not None:
                return value, cls
        return self._span_consistent_difference()

    def _chain_leg_refused(self, result: CompositionResult) -> bool:
        """A chain capex leg is refused when its concept is one the capex
        definition excludes and the leg carries an amount."""
        return any(
            operand.term == "capex"
            and self._capex_operand_refused(operand.concept_qname, operand.value)
            for operand in result.operands
        )

    def _capex_operand_refused(self, qname: str | None, value: float | None) -> bool:
        """A capex operand is refused when its concept is one the capex
        definition excludes and the operand carries an amount."""
        if not value:
            return False
        record = self._records.get(qname or "")
        return record is not None and bool(CAPEX_EXCLUDED_MODS & record.atom.modifiers)

    def _classed_cash_difference(
        self, length_class: str
    ) -> tuple[float | None, str | None]:
        """cfo - capex at one exact class, latest year both legs serve."""
        ocf_series = self._series_at_class(
            "H_CASH", {"M_OPERATING"}, OCF_EXCLUDED_MODS, length_class=length_class
        )
        capex_series = self._capex_series_at_class(length_class)
        shared = sorted(set(ocf_series) & set(capex_series))
        if not shared:
            return None, None
        year = shared[-1]
        return ocf_series[year] - abs(capex_series[year]), length_class

    def _span_consistent_difference(self) -> tuple[float | None, str | None]:
        """cfo - capex when both operands serve one non-annual span class,
        with the composition chain's guards applied to the served legs."""
        cfo, cfo_class, cfo_year = self._operating_cash_flow_served()
        capex, capex_class = self._capex_served()
        if cfo is None or capex is None:
            return None, None
        if capex_class in (None, "ANNUAL") or cfo_class != capex_class:
            return None, None
        if self._span_legs_refused(capex_class, cfo_year, capex):
            return None, None
        return cfo - abs(capex), capex_class

    def _span_legs_refused(
        self, span_class: str, cfo_year: str | None, capex: float
    ) -> bool:
        """The chain's guards over the span difference's two served legs."""
        capex_series = self._capex_series_at_class(span_class)
        capex_winners = self._capex_winners_at_class(span_class)
        capex_qname = capex_winners.get(max(capex_series)) if capex_series else None
        if capex_qname is None or self._capex_operand_refused(capex_qname, capex):
            return True
        cfo_qname = self._operating_leg_qname(span_class, cfo_year)
        if cfo_qname is None:
            return True
        outcome = AntiChainValidator().verify_non_double_counting(
            [cfo_qname, capex_qname],
            [(a.parent_qname, a.child_qname, a.weight) for a in self._arcs],
        )
        return bool(outcome.violations)

    def _operating_leg_qname(self, span_class: str, cfo_year: str | None) -> str | None:
        """The concept the operating leg served from: graph root or pool winner."""
        cf = self._kernel.compose_cash_flow()
        if cf.cfo is not None:
            root = cf.operating.root if cf.operating is not None else None
            return root.concept_qname if root is not None else None
        if cfo_year is None:
            return None
        winners = self._series_winners_at_class(
            "H_CASH", {"M_OPERATING"}, OCF_EXCLUDED_MODS, length_class=span_class
        )
        return winners.get(cfo_year)
