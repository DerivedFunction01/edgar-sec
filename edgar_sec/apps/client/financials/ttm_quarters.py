"""Discrete-quarter derivation from reported cumulative spans.

Reported quarters stand as filed; a later cumulative span yields its
quarter by differencing consecutive legs in the chain.
"""

from __future__ import annotations

from datetime import date, timedelta

from edgar_sec.apps.client.financials.ttm_types import SpanLeg


def _next_day(iso: str) -> str:
    """The ISO date one day after the given ISO date."""
    return (date.fromisoformat(iso) + timedelta(days=1)).isoformat()


def _prior_day(iso: str) -> str:
    """The ISO date one day before the given ISO date."""
    return (date.fromisoformat(iso) - timedelta(days=1)).isoformat()


def _discrete_quarters(
    reported: dict[tuple[str, str], SpanLeg], *, weighted: bool
) -> tuple[dict[tuple[str, str], SpanLeg], list[str]]:
    """Discrete quarters from reported spans, with chain breaks named:
    reported quarters stand as filed, and a later cumulative span yields
    its quarter by differencing consecutive legs (day-weighted if weighted).
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
