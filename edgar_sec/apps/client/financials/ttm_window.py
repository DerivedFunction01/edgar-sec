"""TTM window closing: the routes that close four quarters at one
period end, and the reconciliation when the routes disagree.
"""

from __future__ import annotations

from datetime import date

from edgar_sec.apps.client.financials.ttm_quarters import _prior_day
from edgar_sec.apps.client.financials.ttm_types import (
    QuarterLegSet,
    SpanLeg,
    TtmResult,
)
from edgar_sec.engine.xbrl.solve.core.query import QueryStatus


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
