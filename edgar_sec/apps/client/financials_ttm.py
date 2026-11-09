"""TTM derivation over the financials core.

Quarter legs are selected at span level with the served-series atom
filter; a TTM closes only when its four quarters are accounted for.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from edgar_sec.apps.client.financials_capex import (
    CAPEX_EXCLUDED_MODS,
    CAPEX_PURCHASE_ACT_MODS,
    CAPEX_PURCHASE_MODS,
)
from edgar_sec.apps.client.financials_cash import CashFlowServing
from edgar_sec.apps.client.financials_core import (
    _SHARES_ATOMS,
    OCF_EXCLUDED_MODS,
    REVENUE_EXCLUDED_MODS,
    _calc_distance,
)
from edgar_sec.engine.xbrl.normalize.normalization import normalize_time_coordinate
from edgar_sec.engine.xbrl.schema.models import XbrlFact, split_concept_qname
from edgar_sec.engine.xbrl.solve.query import QueryStatus
from edgar_sec.engine.xbrl.solve.statement import period_rank
from edgar_sec.engine.xbrl.taxonomy.archive import standard_prefixes


_TTM_CLASSES = ("QUARTER", "YTD_2Q", "YTD_3Q", "ANNUAL")
_BASIS = "as-reported; no split adjustment"


@dataclass(frozen=True)
class SpanLeg:
    """One duration span's value for a metric, reported or derived."""

    start: str
    end: str
    length_class: str
    value: float
    accession: str
    concept_qname: str
    unit: str | None
    derived: bool = False
    inputs: tuple[SpanLeg, ...] = ()

    @property
    def days(self) -> int:
        """Span length in days, on the time-coordinate convention."""
        return (date.fromisoformat(self.end) - date.fromisoformat(self.start)).days


@dataclass(frozen=True)
class QuarterLegSet:
    """A metric's reported span legs, its discrete quarters, its breaks."""

    reported: tuple[SpanLeg, ...]
    quarters: tuple[SpanLeg, ...]
    breaks: tuple[str, ...]


@dataclass(frozen=True)
class TtmResult:
    """A statused TTM answer: DERIVED with its legs, or UNAVAILABLE."""

    metric: str
    value: float | None
    status: QueryStatus
    period_end: str | None
    legs: tuple[SpanLeg, ...] = ()
    missing: tuple[str, ...] = ()
    route: str | None = None
    basis: str = _BASIS
    reason: str | None = None
    detail: str | None = None


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


def _length_class(fact: XbrlFact) -> str | None:
    """A duration fact's length class; None when it carries no span."""
    if not fact.start_date or not fact.end_date:
        return None
    return normalize_time_coordinate(
        fact.period_type, fact.instant_date, fact.start_date, fact.end_date
    ).length_class


def _next_day(iso: str) -> str:
    """The ISO date one day after the given ISO date."""
    return (date.fromisoformat(iso) + timedelta(days=1)).isoformat()


def _prior_day(iso: str) -> str:
    """The ISO date one day before the given ISO date."""
    return (date.fromisoformat(iso) - timedelta(days=1)).isoformat()


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

        The end defaults to the latest period end the filing's legs
        reach. A TTM is DERIVED however reported its legs are; an end
        whose four quarters cannot be accounted for is UNAVAILABLE.
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
        """Span legs under one atom filter, served-series selection per span.

        Per concept the longest-span/finest-decimals fact stands, as in
        the kernel's best-ranked scan; per span the winner mirrors the
        served series' rule, with the revenue ancestor yield applied.
        """
        grouped: dict[tuple[str, str], list[XbrlFact]] = {}
        for fact in self._facts:
            if fact.dimensions or fact.period_type != "duration":
                continue
            if not isinstance(fact.value, (int, float)):
                continue
            if fact.unit in ("pure", "shares", "item", "ratio"):
                continue
            if _length_class(fact) not in _TTM_CLASSES:
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
                length_class=_length_class(winner) or "",
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


def _identity_route(
    reported: dict[tuple[str, str], SpanLeg], end: str, *, weighted: bool
) -> tuple[float, tuple[SpanLeg, ...]] | None:
    """FY + current YTD − prior YTD over the reported cumulative legs."""
    candidates = [
        leg
        for leg in reported.values()
        if leg.end == end and leg.length_class != "ANNUAL"
    ]
    if not candidates:
        return None
    current = max(candidates, key=lambda leg: leg.days)
    annual = next(
        (
            leg
            for leg in reported.values()
            if leg.length_class == "ANNUAL" and leg.end == _prior_day(current.start)
        ),
        None,
    )
    if annual is None:
        return None
    priors = [
        leg
        for leg in reported.values()
        if leg.start == annual.start and leg.length_class == current.length_class
    ]
    if not priors:
        return None
    prior = priors[0]
    if (
        annual.concept_qname != current.concept_qname
        or current.concept_qname != prior.concept_qname
        or annual.unit != current.unit
        or current.unit != prior.unit
    ):
        return None
    if weighted:
        denominator = annual.days + current.days - prior.days
        if denominator <= 0:
            return None
        value = (
            annual.value * annual.days
            + current.value * current.days
            - prior.value * prior.days
        ) / denominator
    else:
        value = annual.value + current.value - prior.value
    return value, (annual, current, prior)


def _ttm_window(
    metric: str,
    leg_set: QuarterLegSet,
    *,
    weighted: bool,
    period_end: str | None,
) -> TtmResult:
    """Close the four-quarter window at one period end, or name the gap."""
    ends = [leg.end for leg in leg_set.reported] + [leg.end for leg in leg_set.quarters]
    end = period_end or (max(ends) if ends else None)
    if end is None:
        return TtmResult(
            metric=metric,
            value=None,
            status=QueryStatus.UNAVAILABLE,
            period_end=None,
            reason="the filing carries no duration legs for this metric",
        )
    routes: dict[str, tuple[float, tuple[SpanLeg, ...]]] = {}
    for leg in leg_set.reported:
        if leg.length_class == "ANNUAL" and leg.end == end:
            routes["annual_span"] = (leg.value, (leg,))
    by_end: dict[str, SpanLeg] = {}
    for leg in leg_set.quarters:
        current = by_end.get(leg.end)
        if current is None or (current.derived and not leg.derived):
            by_end[leg.end] = leg
    chain: list[SpanLeg] = []
    cursor = end
    missing_end: str | None = None
    for _ in range(4):
        quarter = by_end.get(cursor)
        if quarter is None:
            missing_end = cursor
            break
        chain.append(quarter)
        cursor = _prior_day(quarter.start)
    if missing_end is None and len(chain) == 4:
        window_days = (
            date.fromisoformat(end) - date.fromisoformat(chain[-1].start)
        ).days
        if 330 <= window_days <= 390:
            if weighted:
                total_days = sum(quarter.days for quarter in chain)
                value = (
                    sum(quarter.value * quarter.days for quarter in chain) / total_days
                )
            else:
                value = sum(quarter.value for quarter in chain)
            routes["direct_four_quarter"] = (value, tuple(reversed(chain)))
    reported = {(leg.start, leg.end): leg for leg in leg_set.reported}
    identity = _identity_route(reported, end, weighted=weighted)
    if identity is not None:
        routes["fiscal_year_identity"] = identity
    if not routes:
        missing = (f"quarter ending {missing_end or end}",)
        reason = f"no TTM route closes at {end}"
        if leg_set.breaks:
            reason += "; " + "; ".join(leg_set.breaks)
        return TtmResult(
            metric=metric,
            value=None,
            status=QueryStatus.UNAVAILABLE,
            period_end=end,
            missing=missing,
            reason=reason,
        )
    values = [value for value, _legs in routes.values()]
    tolerance = max(0.01, 1e-6 * max(abs(value) for value in values))
    if max(values) - min(values) > tolerance:
        detail = ", ".join(
            f"{name}={value}" for name, (value, _legs) in sorted(routes.items())
        )
        return TtmResult(
            metric=metric,
            value=None,
            status=QueryStatus.UNAVAILABLE,
            period_end=end,
            reason=f"the TTM routes that close at {end} disagree",
            detail=detail,
        )
    for name in ("direct_four_quarter", "annual_span", "fiscal_year_identity"):
        if name in routes:
            value, legs = routes[name]
            detail = None
            if len(routes) > 1:
                detail = "routes agree: " + ", ".join(sorted(routes))
            return TtmResult(
                metric=metric,
                value=value,
                status=QueryStatus.DERIVED,
                period_end=end,
                legs=legs,
                route=name,
                detail=detail,
            )
    raise AssertionError("unreachable: routes non-empty but none selected")


def _discrete_quarters(
    reported: dict[tuple[str, str], SpanLeg], *, weighted: bool
) -> tuple[dict[tuple[str, str], SpanLeg], list[str]]:
    """Discrete quarters from reported spans, with chain breaks named.

    Reported quarters stand as filed; a later cumulative span in a
    chain yields its quarter as the difference of consecutive legs.
    Weighted legs difference their day-weighted totals instead.
    """
    quarters: dict[tuple[str, str], SpanLeg] = {}
    breaks: list[str] = []
    for span, leg in reported.items():
        if leg.length_class == "QUARTER":
            quarters[span] = leg
    chains: dict[str, list[SpanLeg]] = {}
    for leg in reported.values():
        chains.setdefault(leg.start, []).append(leg)
    ranks = {"QUARTER": 1, "YTD_2Q": 2, "YTD_3Q": 3, "ANNUAL": 4}
    for start in sorted(chains):
        legs = sorted(chains[start], key=lambda leg: leg.end)
        prev: SpanLeg | None = None
        for leg in legs:
            if prev is None:
                if leg.length_class != "QUARTER":
                    breaks.append(
                        f"{leg.start}..{leg.end}: the chain opens at "
                        f"{leg.length_class} with no earlier cumulative "
                        "leg; its first quarter cannot be separated"
                    )
                prev = leg
                continue
            span = (_next_day(prev.end), leg.end)
            if span in quarters:
                prev = leg
                continue
            if ranks[leg.length_class] != ranks[prev.length_class] + 1:
                breaks.append(
                    f"{span[0]}..{span[1]}: the cumulative legs jump "
                    f"from {prev.length_class} to {leg.length_class}; "
                    "the intervening quarters cannot be separated"
                )
                prev = leg
                continue
            if leg.concept_qname != prev.concept_qname or leg.unit != prev.unit:
                breaks.append(
                    f"{span[0]}..{span[1]}: the cumulative legs change "
                    f"concept or unit ({prev.concept_qname} -> "
                    f"{leg.concept_qname}); the difference is refused"
                )
                prev = leg
                continue
            if weighted:
                if leg.days <= prev.days:
                    breaks.append(
                        f"{span[0]}..{span[1]}: the cumulative span does "
                        "not lengthen; the weighted difference is refused"
                    )
                    prev = leg
                    continue
                value = (leg.value * leg.days - prev.value * prev.days) / (
                    leg.days - prev.days
                )
            else:
                value = leg.value - prev.value
            quarters[span] = SpanLeg(
                start=span[0],
                end=span[1],
                length_class="QUARTER",
                value=value,
                accession=leg.accession,
                concept_qname=leg.concept_qname,
                unit=leg.unit,
                derived=True,
                inputs=(prev, leg),
            )
            prev = leg
    return quarters, breaks
