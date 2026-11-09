"""Cross-filing TTM over the stitched series.

The within-filing window runs unchanged over legs adapted from the
stitched series: reported legs mirror the served-series span
selection, and derived quarters enter only where un-accumulation
derived them from the selected legs themselves.
"""

from __future__ import annotations

from edgar_sec.apps.client.financials_core import _SHARES_ATOMS
from edgar_sec.apps.client.financials_ttm import (
    _EPS_METRICS,
    _FLOW_GROUPS,
    _INSTANT_METRICS,
    _SHARE_METRICS,
    _TTM_CLASSES,
    QuarterLegSet,
    SpanLeg,
    TtmResult,
    _AtomFilter,
    _discrete_quarters,
    _ttm_window,
)
from edgar_sec.engine.xbrl.normalize.decomposer import decompose_concept
from edgar_sec.engine.xbrl.normalize.normalization import normalize_time_coordinate
from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.solve.assembly import StitchedSeries
from edgar_sec.engine.xbrl.solve.query import QueryStatus
from edgar_sec.engine.xbrl.solve.stitched import DerivationInput, StitchedValue
from edgar_sec.engine.xbrl.solve.tokenizer import ConceptTokenizer
from edgar_sec.engine.xbrl.solve.unaccumulate import derive_discrete_quarters
from edgar_sec.engine.xbrl.taxonomy.domain import (
    DomainTaxonomy,
    load_domain_taxonomy,
)

_EXCLUDED_UNITS = ("pure", "shares", "item", "ratio")


class _SeriesAtoms:
    """Atom resolution over a series' concepts, tokenized once each."""

    def __init__(self, taxonomy: DomainTaxonomy) -> None:
        self._lexicon = taxonomy.token_lexicon
        self._tokenizer = (
            ConceptTokenizer(taxonomy) if self._lexicon is not None else None
        )
        self._atoms: dict[str, Atom | None] = {}
        self._decomposed: dict[str, Atom | None] = {}

    def atom(self, qname: str) -> Atom | None:
        """The tokenizer atom for one concept, as the kernel fallback reads it."""
        if qname not in self._atoms:
            if self._tokenizer is None:
                self._atoms[qname] = None
            else:
                self._atoms[qname] = self._tokenizer.tokenize(qname).atom
        return self._atoms[qname]

    def decomposed(self, qname: str) -> Atom | None:
        """The decomposer atom for one concept, as the EPS slots read it."""
        if qname not in self._decomposed:
            if self._lexicon is None:
                self._decomposed[qname] = None
            else:
                atom, _residuals, _head, _tail = decompose_concept(qname, self._lexicon)
                self._decomposed[qname] = atom
        return self._decomposed[qname]


def _class_of(start: str | None, end: str | None) -> str | None:
    """A duration span's length class; None when it carries no span."""
    if not start or not end:
        return None
    return normalize_time_coordinate("duration", None, start, end).length_class


def _candidates(series: StitchedSeries) -> list[StitchedValue]:
    """Series values that can carry a flow leg: duration, undimensioned, valued."""
    return [
        value
        for value in series.values
        if value.period_type == "duration"
        and not value.dimensions
        and value.value is not None
        and _class_of(value.start_date, value.end_date) in _TTM_CLASSES
    ]


def _legs_for_filter(
    values: list[StitchedValue], flt: _AtomFilter, atoms: _SeriesAtoms
) -> dict[tuple[str, str], SpanLeg]:
    """Span legs under one atom filter, the served-series winner per span.

    Mirrors the within-filing selection over series values: the span
    pool competes under the same winner rule, bare preferred or the
    largest magnitude, with the absolute-value adjustment applied.
    """
    grouped: dict[tuple[str, str], list[StitchedValue]] = {}
    for value in values:
        if value.unit in _EXCLUDED_UNITS:
            continue
        if flt.concept is not None:
            if value.concept_qname != flt.concept:
                continue
        else:
            atom = atoms.atom(value.concept_qname)
            if atom is None or atom.head != flt.head:
                continue
            if not flt.mods.issubset(atom.modifiers):
                continue
            if flt.excluded and flt.excluded & atom.modifiers:
                continue
            if flt.valence and flt.valence not in atom.modifiers:
                continue
        span = (value.start_date or "", value.end_date or "")
        grouped.setdefault(span, []).append(value)
    legs: dict[tuple[str, str], SpanLeg] = {}
    for span, pool in grouped.items():
        per_concept: dict[str, StitchedValue] = {}
        for value in pool:
            per_concept.setdefault(value.concept_qname, value)
        winner: StitchedValue | None = None
        winner_cand: tuple[int, float, float] | None = None
        for value in per_concept.values():
            atom = atoms.atom(value.concept_qname)
            mods = len(atom.modifiers) if atom is not None else 0
            number = float(value.value) if value.value is not None else 0.0
            cand = (mods, -abs(number), number)
            if winner is None or winner_cand is None:
                winner, winner_cand = value, cand
            elif flt.prefer_bare and cand < winner_cand:
                winner, winner_cand = value, cand
            elif not flt.prefer_bare and abs(number) > abs(winner_cand[2]):
                winner, winner_cand = value, cand
        if winner is None or winner.value is None:
            continue
        number = float(winner.value)
        if flt.absolute:
            number = abs(number)
        legs[span] = SpanLeg(
            start=span[0],
            end=span[1],
            length_class=_class_of(span[0], span[1]) or "",
            value=number,
            accession=winner.source_accession,
            concept_qname=winner.concept_qname,
            unit=winner.unit,
        )
    return legs


def _reported_legs(
    metric: str, values: list[StitchedValue], atoms: _SeriesAtoms
) -> dict[tuple[str, str], SpanLeg]:
    """Reported span legs for a flow metric, first live filter group."""
    groups = _FLOW_GROUPS.get(metric)
    if groups is None:
        known = sorted(_FLOW_GROUPS) + ["free_cash_flow", "net_income"]
        raise ValueError(f"unknown metric {metric!r}; expected one of {known}")
    # No statement root exists over a series; net income reads its
    # filter ladder directly, where the filing surface prefers the root.
    for group in groups:
        merged: dict[tuple[str, str], SpanLeg] = {}
        for flt in group:
            merged.update(_legs_for_filter(values, flt, atoms))
        if merged:
            return merged
    return {}


def _series_break_notes(series: StitchedSeries) -> tuple[str, ...]:
    """The series' fiscal-calendar breaks, as window-break notes."""
    return tuple(
        f"series break after {item.after_end} ({item.reason}); no TTM window crosses it"
        for item in series.breaks
    )


def _input_leg(item: DerivationInput, unit: str | None) -> SpanLeg:
    """One derivation input as a leg, on the derived leg's unit."""
    return SpanLeg(
        start=item.start_date or "",
        end=item.end_date or "",
        length_class=_class_of(item.start_date, item.end_date) or "",
        value=float(item.value) if item.value is not None else 0.0,
        accession=item.accession,
        concept_qname=item.concept_qname,
        unit=unit,
    )


def _flow_leg_set(
    series: StitchedSeries, metric: str, atoms: _SeriesAtoms
) -> QuarterLegSet:
    """A flow metric's stitched leg set: reported legs, quarters, breaks.

    A derived quarter enters only when both of its derivation inputs
    are legs the span selection itself picked, so an unselected
    concept's chain never reaches the window.
    """
    reported = _reported_legs(metric, _candidates(series), atoms)
    quarters: dict[tuple[str, str], SpanLeg] = {
        span: leg for span, leg in reported.items() if leg.length_class == "QUARTER"
    }
    winning = {(leg.concept_qname, leg.start, leg.end) for leg in reported.values()}
    selected = {leg.concept_qname for leg in reported.values()}
    derivation = derive_discrete_quarters(series)
    for item in derivation.derived:
        if item.value is None:
            continue
        span = (item.start_date or "", item.end_date or "")
        if span in quarters:
            continue
        if any(part.value is None for part in item.derivation_inputs):
            continue
        if not all(
            (part.concept_qname, part.start_date, part.end_date) in winning
            for part in item.derivation_inputs
        ):
            continue
        quarters[span] = SpanLeg(
            start=span[0],
            end=span[1],
            length_class="QUARTER",
            value=float(item.value),
            accession=item.source_accession,
            concept_qname=item.concept_qname,
            unit=item.unit,
            derived=True,
            inputs=tuple(
                _input_leg(part, item.unit) for part in item.derivation_inputs
            ),
        )
    breaks = [
        f"{refusal.start_date}..{refusal.end_date}: un-accumulation "
        f"refused for {refusal.concept_qname} ({refusal.reason})"
        for refusal in derivation.refusals
        if refusal.concept_qname in selected
    ]
    return QuarterLegSet(
        reported=tuple(sorted(reported.values(), key=lambda leg: leg.end)),
        quarters=tuple(sorted(quarters.values(), key=lambda leg: leg.end)),
        breaks=tuple(breaks) + _series_break_notes(series),
    )


def _share_leg_set(
    series: StitchedSeries, *, diluted: bool, atoms: _SeriesAtoms
) -> QuarterLegSet:
    """Weighted-share legs from reported spans, quarters day-differenced.

    Un-accumulation never feeds a share leg: the quarters difference
    the reported cumulative spans by day counts, exactly as the
    within-filing surface derives them (the Step 6 proof narrowing).
    """
    target = _SHARES_ATOMS[diluted]
    by_span: dict[tuple[str, str], list[StitchedValue]] = {}
    for value in series.values:
        if value.period_type != "duration" or value.dimensions:
            continue
        if value.value is None:
            continue
        if _class_of(value.start_date, value.end_date) not in _TTM_CLASSES:
            continue
        if atoms.decomposed(value.concept_qname) != target:
            continue
        span = (value.start_date or "", value.end_date or "")
        by_span.setdefault(span, []).append(value)
    order = {accession: index for index, accession in enumerate(series.accessions)}
    reported: dict[tuple[str, str], SpanLeg] = {}
    for span, pool in by_span.items():
        distinct = {float(value.value) for value in pool if value.value is not None}
        if len(distinct) != 1:
            continue
        chosen = max(pool, key=lambda value: order.get(value.source_accession, -1))
        if chosen.value is None:
            continue
        reported[span] = SpanLeg(
            start=span[0],
            end=span[1],
            length_class=_class_of(span[0], span[1]) or "",
            value=float(chosen.value),
            accession=chosen.source_accession,
            concept_qname=chosen.concept_qname,
            unit=chosen.unit,
        )
    quarters, breaks = _discrete_quarters(reported, weighted=True)
    return QuarterLegSet(
        reported=tuple(sorted(reported.values(), key=lambda leg: leg.end)),
        quarters=tuple(sorted(quarters.values(), key=lambda leg: leg.end)),
        breaks=tuple(breaks) + _series_break_notes(series),
    )


def _fcf_leg_set(series: StitchedSeries, atoms: _SeriesAtoms) -> QuarterLegSet:
    """Free-cash-flow legs from span-aligned stitched CFO and capex legs."""
    cfo = _flow_leg_set(series, "operating_cash_flow", atoms)
    capex = _flow_leg_set(series, "capex", atoms)
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


def _segment_index(series: StitchedSeries, end: str) -> int:
    """The calendar segment a period end falls in, by the series' breaks."""
    return sum(1 for item in series.breaks if item.after_end < end)


def _restrict_to_segment(
    series: StitchedSeries, leg_set: QuarterLegSet, end: str
) -> QuarterLegSet:
    """The leg set bounded to the target end's calendar segment (D4)."""
    if not series.breaks:
        return leg_set
    index = _segment_index(series, end)

    def inside(leg: SpanLeg) -> bool:
        if _segment_index(series, leg.end) != index:
            return False
        return all(
            not (leg.start <= item.after_end < leg.end) for item in series.breaks
        )

    return QuarterLegSet(
        reported=tuple(leg for leg in leg_set.reported if inside(leg)),
        quarters=tuple(leg for leg in leg_set.quarters if inside(leg)),
        breaks=leg_set.breaks,
    )


def stitched_quarter_legs(
    series: StitchedSeries,
    metric: str,
    *,
    taxonomy: DomainTaxonomy | None = None,
) -> QuarterLegSet:
    """A metric's leg set over the stitched series, provenance intact.

    Instant and per-share metrics have no quarter legs, as on the
    filing surface: instant metrics serve their instant value, EPS
    serves as a ratio of the two stitched TTM legs.
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
    atoms = _SeriesAtoms(taxonomy or load_domain_taxonomy())
    if metric == "free_cash_flow":
        return _fcf_leg_set(series, atoms)
    if metric in _SHARE_METRICS:
        return _share_leg_set(series, diluted=_SHARE_METRICS[metric], atoms=atoms)
    return _flow_leg_set(series, metric, atoms)


def stitched_ttm(
    series: StitchedSeries,
    metric: str,
    *,
    period_end: str | None = None,
    taxonomy: DomainTaxonomy | None = None,
) -> TtmResult:
    """The trailing twelve months over the stitched series, statused.

    DERIVED however reported its legs are; an end whose four quarters
    are not all accounted for within its calendar segment is
    UNAVAILABLE naming the missing quarter.
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
    resolved = taxonomy or load_domain_taxonomy()
    if metric in _EPS_METRICS:
        return _eps_ttm(series, metric, period_end=period_end, taxonomy=resolved)
    leg_set = stitched_quarter_legs(series, metric, taxonomy=resolved)
    ends = [leg.end for leg in leg_set.reported] + [leg.end for leg in leg_set.quarters]
    end = period_end or (max(ends) if ends else None)
    if end is None:
        return TtmResult(
            metric=metric,
            value=None,
            status=QueryStatus.UNAVAILABLE,
            period_end=None,
            reason="the stitched series carries no duration legs for this metric",
        )
    bounded = _restrict_to_segment(series, leg_set, end)
    return _ttm_window(
        metric, bounded, weighted=metric in _SHARE_METRICS, period_end=end
    )


def _eps_ttm(
    series: StitchedSeries,
    metric: str,
    *,
    period_end: str | None,
    taxonomy: DomainTaxonomy,
) -> TtmResult:
    """EPS TTM as stitched net income over stitched weighted shares.

    Quarterly EPS never sums: the ratio of the two TTM legs is the
    only per-share TTM, on the as-reported basis (D3).
    """
    diluted = metric == "eps_diluted"
    shares_metric = "weighted_shares_diluted" if diluted else "weighted_shares_basic"
    income = stitched_ttm(
        series, "net_income", period_end=period_end, taxonomy=taxonomy
    )
    shares = stitched_ttm(
        series, shares_metric, period_end=period_end, taxonomy=taxonomy
    )
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
