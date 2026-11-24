"""TTM derivation over the financials core.

Quarter legs are selected at span level with the served-series atom
filter; a TTM closes only when its four quarters are accounted for.
"""

from __future__ import annotations

from edgar_sec.apps.client.financials.financials_cash import CashFlowServing
from edgar_sec.apps.client.financials.financials_eps import _SHARES_ATOMS
from edgar_sec.apps.client.financials.financials_series import (
    OCF_EXCLUDED_MODS,
    REVENUE_EXCLUDED_MODS,
    _calc_distance,
)
from edgar_sec.apps.client.financials.ttm_filters import (
    _EPS_METRICS,
    _FLOW_GROUPS,
    _INSTANT_METRICS,
    _SHARE_METRICS,
    _TTM_CLASSES,
    _AtomFilter,
)
from edgar_sec.apps.client.financials.ttm_quarters import _discrete_quarters
from edgar_sec.apps.client.financials.ttm_types import (
    QuarterLegSet,
    SpanLeg,
    TtmResult,
)
from edgar_sec.apps.client.financials.ttm_window import _ttm_window
from edgar_sec.apps.client.core.kernel import _span_length_class
from edgar_sec.engine.xbrl.schema.models import XbrlFact, split_concept_qname
from edgar_sec.engine.xbrl.solve.core.query import QueryStatus
from edgar_sec.engine.xbrl.solve.statements.statement import period_rank
from edgar_sec.engine.xbrl.taxonomy.archive import standard_prefixes


class TtmServing(CashFlowServing):
    """Quarter-leg selection and TTM derivation over one filing's facts."""

    def quarter_legs(self, metric: str) -> QuarterLegSet:
        """A metric's span legs and discrete quarters within this filing.

        Instant and per-share metrics have no quarter legs: instant
        metrics serve their instant value, EPS serves as a ratio.
        """
        if metric in _INSTANT_METRICS or metric == "uncommenced_leases":
            raise ValueError(
                f"metric {metric!r} is an instant metric; it has no quarter legs"
            )
        if metric in _EPS_METRICS:
            raise ValueError(
                f"metric {metric!r} is per-share; its TTM is a derived ratio, "
                "not a sum of quarter legs"
            )
        return self._kernel.graph_once(
            ("ttm_quarter_legs", metric), lambda: self._build_quarter_legs(metric)
        )

    def ttm(self, metric: str, *, period_end: str | None = None) -> TtmResult:
        """The trailing twelve months ending at a period end, statused.
        DERIVED however reported its legs are; an end missing one of its
        four quarters is UNAVAILABLE. The end defaults to the latest reached.
        """
        if metric in _INSTANT_METRICS or metric == "uncommenced_leases":
            return TtmResult(
                metric=metric,
                value=None,
                status=QueryStatus.UNAVAILABLE,
                period_end=period_end,
                reason=(
                    f"{metric} is an instant metric; TTM applies to duration flows only"
                ),
            )
        if metric in _EPS_METRICS:
            return self._eps_ttm(metric, period_end=period_end)
        leg_set = self.quarter_legs(metric)
        weighted = metric in _SHARE_METRICS
        return _ttm_window(metric, leg_set, weighted=weighted, period_end=period_end)

    def _eps_ttm(self, metric: str, *, period_end: str | None = None) -> TtmResult:
        """EPS TTM as TTM net income over TTM weighted shares.

        Quarterly EPS never sums: the ratio of the two TTM legs is
        the only per-share TTM, on the as-reported basis (D3).
        """
        diluted = metric == "eps_diluted"
        shares_metric = (
            "weighted_shares_diluted" if diluted else "weighted_shares_basic"
        )
        income = self.ttm("net_income", period_end=period_end)
        shares = self.ttm(shares_metric, period_end=period_end)
        if income.value is None or shares.value is None or shares.value == 0:
            failed = income if income.value is None else shares
            return TtmResult(
                metric=metric,
                value=None,
                status=QueryStatus.UNAVAILABLE,
                period_end=period_end,
                missing=failed.missing,
                reason=(f"the {failed.metric} TTM leg does not close: {failed.reason}"),
            )
        if income.period_end != shares.period_end:
            return TtmResult(
                metric=metric,
                value=None,
                status=QueryStatus.UNAVAILABLE,
                period_end=period_end,
                reason=(
                    "the net income and weighted shares TTM legs close "
                    f"at different period ends ({income.period_end} vs "
                    f"{shares.period_end})"
                ),
            )
        return TtmResult(
            metric=metric,
            value=round(income.value / shares.value, 4),
            status=QueryStatus.DERIVED,
            period_end=income.period_end,
            detail=(
                f"net_income TTM {income.value} / {shares_metric} TTM "
                f"{shares.value}; as-reported basis, no split adjustment"
            ),
        )

    def revenue_ttm(self, *, period_end: str | None = None) -> TtmResult:
        """Revenue over the trailing twelve months, statused."""
        return self.ttm("revenue", period_end=period_end)

    def gross_profit_ttm(self, *, period_end: str | None = None) -> TtmResult:
        """Gross profit over the trailing twelve months, statused."""
        return self.ttm("gross_profit", period_end=period_end)

    def operating_income_ttm(self, *, period_end: str | None = None) -> TtmResult:
        """Operating income over the trailing twelve months, statused."""
        return self.ttm("operating_income", period_end=period_end)

    def net_income_ttm(self, *, period_end: str | None = None) -> TtmResult:
        """Net income over the trailing twelve months, statused."""
        return self.ttm("net_income", period_end=period_end)

    def operating_cash_flow_ttm(self, *, period_end: str | None = None) -> TtmResult:
        """Operating cash flow over the trailing twelve months, statused."""
        return self.ttm("operating_cash_flow", period_end=period_end)

    def capex_ttm(self, *, period_end: str | None = None) -> TtmResult:
        """Capex over the trailing twelve months, statused."""
        return self.ttm("capex", period_end=period_end)

    def free_cash_flow_ttm(self, *, period_end: str | None = None) -> TtmResult:
        """Free cash flow over the trailing twelve months, statused."""
        return self.ttm("free_cash_flow", period_end=period_end)

    def eps_basic_ttm(self, *, period_end: str | None = None) -> TtmResult:
        """Basic EPS TTM as a derived ratio, never a sum of quarters."""
        return self.ttm("eps_basic", period_end=period_end)

    def eps_diluted_ttm(self, *, period_end: str | None = None) -> TtmResult:
        """Diluted EPS TTM as a derived ratio, never a sum of quarters."""
        return self.ttm("eps_diluted", period_end=period_end)

    def weighted_shares_basic_ttm(self, *, period_end: str | None = None) -> TtmResult:
        """Basic weighted shares over the TTM window, day-weighted."""
        return self.ttm("weighted_shares_basic", period_end=period_end)

    def weighted_shares_diluted_ttm(
        self, *, period_end: str | None = None
    ) -> TtmResult:
        """Diluted weighted shares over the TTM window, day-weighted."""
        return self.ttm("weighted_shares_diluted", period_end=period_end)

    def _build_quarter_legs(self, metric: str) -> QuarterLegSet:
        """Assemble one metric's leg set from its reported spans."""
        if metric == "free_cash_flow":
            return self._fcf_quarter_legs()
        if metric in _SHARE_METRICS:
            reported = self._share_span_legs(diluted=_SHARE_METRICS[metric])
            quarters, breaks = _discrete_quarters(reported, weighted=True)
            return QuarterLegSet(
                reported=tuple(sorted(reported.values(), key=lambda leg: leg.end)),
                quarters=tuple(sorted(quarters.values(), key=lambda leg: leg.end)),
                breaks=tuple(breaks),
            )
        reported = self._reported_legs(metric)
        quarters, breaks = _discrete_quarters(reported, weighted=False)
        return QuarterLegSet(
            reported=tuple(sorted(reported.values(), key=lambda leg: leg.end)),
            quarters=tuple(sorted(quarters.values(), key=lambda leg: leg.end)),
            breaks=tuple(breaks),
        )

    def _reported_legs(self, metric: str) -> dict[tuple[str, str], SpanLeg]:
        """Reported span legs for a flow metric, first live filter group."""
        groups = _FLOW_GROUPS.get(metric)
        if groups is None:
            if metric == "net_income":
                groups = ()
            else:
                known = sorted(_FLOW_GROUPS) + [
                    "free_cash_flow",
                    "net_income",
                ]
                raise ValueError(f"unknown metric {metric!r}; expected one of {known}")
        if metric == "net_income":
            root = self._kernel.compose_income_statement().root_qname
            if root:
                rooted = self._legs_for_filter(_AtomFilter("", concept=root))
                if rooted:
                    return rooted
        for group in groups:
            merged: dict[tuple[str, str], SpanLeg] = {}
            for flt in group:
                merged.update(self._legs_for_filter(flt))
            if merged:
                return merged
        return {}

    def _legs_for_filter(self, flt: _AtomFilter) -> dict[tuple[str, str], SpanLeg]:
        """Span legs under one atom filter, served-series selection per span:
        the longest-span/finest-decimals fact stands per concept, and the
        per-span winner mirrors the served series, revenue ancestor yielding.
        """
        grouped: dict[tuple[str, str], list[XbrlFact]] = {}
        for fact in self._facts:
            if fact.dimensions or fact.period_type != "duration":
                continue
            if not isinstance(fact.value, (int, float)):
                continue
            if fact.unit in ("pure", "shares", "item", "ratio"):
                continue
            if _span_length_class(fact) not in _TTM_CLASSES:
                continue
            record = self._records.get(fact.concept_qname)
            if record is None:
                continue
            atom = record.atom
            if flt.concept is not None:
                if fact.concept_qname != flt.concept:
                    continue
            else:
                if atom.head != flt.head or not flt.mods.issubset(atom.modifiers):
                    continue
                if flt.excluded and flt.excluded & atom.modifiers:
                    continue
                if flt.valence and flt.valence not in atom.modifiers:
                    continue
            grouped.setdefault((fact.start_date, fact.end_date), []).append(fact)
        legs: dict[tuple[str, str], SpanLeg] = {}
        pools: dict[tuple[str, str], list[tuple[str, float]]] = {}
        for span, facts in grouped.items():
            per_concept: dict[str, XbrlFact] = {}
            for fact in facts:
                current = per_concept.get(fact.concept_qname)
                if current is None or period_rank(fact) > period_rank(current):
                    per_concept[fact.concept_qname] = fact
            pools[span] = [
                (qname, float(fact.value)) for qname, fact in per_concept.items()
            ]
            winner: XbrlFact | None = None
            winner_cand: tuple[int, float, float] | None = None
            for fact in per_concept.values():
                atom = self._records[fact.concept_qname].atom
                value = float(fact.value)
                cand = (len(atom.modifiers), -abs(value), value)
                if winner is None or winner_cand is None:
                    winner, winner_cand = fact, cand
                elif flt.prefer_bare and cand < winner_cand:
                    winner, winner_cand = fact, cand
                elif not flt.prefer_bare and abs(value) > abs(winner_cand[2]):
                    winner, winner_cand = fact, cand
            if winner is None:
                continue
            value = float(winner.value)
            if flt.absolute:
                value = abs(value)
            legs[span] = SpanLeg(
                start=span[0],
                end=span[1],
                length_class=_span_length_class(winner) or "",
                value=value,
                accession=str(winner.accession),
                concept_qname=winner.concept_qname,
                unit=winner.unit,
            )
        if flt.head == "H_REVENUE" and not flt.mods and flt.concept is None:
            self._yield_to_standard_ancestors(legs, pools)
        return legs

    def _yield_to_standard_ancestors(
        self,
        legs: dict[tuple[str, str], SpanLeg],
        pools: dict[tuple[str, str], list[tuple[str, float]]],
    ) -> None:
        """Per span, a revenue pick inside a standard total yields to it."""
        standard = standard_prefixes()
        children: dict[str, list[str]] | None = None
        for span, leg in legs.items():
            if split_concept_qname(leg.concept_qname)[0] in standard:
                continue
            candidates = [
                (qname, value)
                for qname, value in pools[span]
                if qname != leg.concept_qname
                and split_concept_qname(qname)[0] in standard
            ]
            if not candidates:
                continue
            if children is None:
                children = self._calc_children()
            ranked = []
            for qname, value in candidates:
                distance = _calc_distance(children, qname, leg.concept_qname)
                if distance is not None:
                    ranked.append((distance, -abs(value), qname, value))
            if not ranked:
                continue
            _distance, _neg, qname, value = min(ranked)
            legs[span] = SpanLeg(
                start=leg.start,
                end=leg.end,
                length_class=leg.length_class,
                value=value,
                accession=leg.accession,
                concept_qname=qname,
                unit=leg.unit,
            )

    def _share_span_legs(self, *, diluted: bool) -> dict[tuple[str, str], SpanLeg]:
        """Filed weighted-share spans, selected by the EPS slot machinery."""
        atoms = self._eps_atoms()
        target = _SHARES_ATOMS[diluted]
        legs: dict[tuple[str, str], SpanLeg] = {}
        for length_class, _year, _span, facts in self._eps_period_groups():
            if length_class not in _TTM_CLASSES:
                continue
            value = self._eps_slot_value(facts, target)
            if value is None:
                continue
            matched = next(
                fact
                for fact in facts
                if atoms.get(fact.concept_qname, (None, 0))[0] == target
            )
            leg = SpanLeg(
                start=matched.start_date or "",
                end=matched.end_date or "",
                length_class=length_class,
                value=value,
                accession=str(matched.accession),
                concept_qname=matched.concept_qname,
                unit=matched.unit,
            )
            legs[(leg.start, leg.end)] = leg
        return legs

    def _fcf_quarter_legs(self) -> QuarterLegSet:
        """Free-cash-flow legs from span-aligned CFO and capex legs."""
        cfo = self._build_quarter_legs("operating_cash_flow")
        capex = self._build_quarter_legs("capex")
        breaks = list(cfo.breaks) + list(capex.breaks)
        capex_reported = {(leg.start, leg.end): leg for leg in capex.reported}
        reported: dict[tuple[str, str], SpanLeg] = {}
        for leg in cfo.reported:
            cap = capex_reported.get((leg.start, leg.end))
            if cap is None:
                continue
            reported[(leg.start, leg.end)] = SpanLeg(
                start=leg.start,
                end=leg.end,
                length_class=leg.length_class,
                value=leg.value - abs(cap.value),
                accession=leg.accession,
                concept_qname=leg.concept_qname,
                unit=leg.unit,
                derived=True,
                inputs=(leg, cap),
            )
        capex_quarters = {(leg.start, leg.end): leg for leg in capex.quarters}
        quarters: dict[tuple[str, str], SpanLeg] = {}
        for leg in cfo.quarters:
            cap = capex_quarters.get((leg.start, leg.end))
            if cap is None:
                breaks.append(
                    f"{leg.start}..{leg.end}: no aligned capex quarter; "
                    "the free-cash-flow quarter is refused"
                )
                continue
            quarters[(leg.start, leg.end)] = SpanLeg(
                start=leg.start,
                end=leg.end,
                length_class="QUARTER",
                value=leg.value - abs(cap.value),
                accession=leg.accession,
                concept_qname=leg.concept_qname,
                unit=leg.unit,
                derived=True,
                inputs=(leg, cap),
            )
        return QuarterLegSet(
            reported=tuple(sorted(reported.values(), key=lambda leg: leg.end)),
            quarters=tuple(sorted(quarters.values(), key=lambda leg: leg.end)),
            breaks=tuple(breaks),
        )
