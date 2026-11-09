"""YTD un-accumulation over a stitched series.

Discrete quarters are derived from cumulative spans within one fiscal
year; a reported quarter always wins over a derived one (D5), and a
chain that cannot close exactly yields a recorded refusal, not a value.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from types import MappingProxyType
from typing import Mapping

from edgar_sec.engine.xbrl.normalize.normalization import normalize_time_coordinate
from edgar_sec.engine.xbrl.solve.assembly import StitchedSeries
from edgar_sec.engine.xbrl.solve.query import QueryStatus
from edgar_sec.engine.xbrl.taxonomy.item_types import is_non_additive_item_type
from edgar_sec.engine.xbrl.solve.stitched import (
    DERIVED_EXACT_BASIS,
    DerivationInput,
    StitchedValue,
)

MISSING_PRIOR_LEG = "missing_prior_leg"
CROSSES_SERIES_BREAK = "crosses_series_break"
AMBIGUOUS_LEG = "ambiguous_leg"
LEG_WITHOUT_VALUE = "leg_without_value"
DERIVED_SPAN_NOT_QUARTER = "derived_span_not_quarter"
NON_ADDITIVE_ITEM_TYPE = "non_additive_item_type"

_RUNGS = {"QUARTER": 1, "YTD_2Q": 2, "YTD_3Q": 3, "ANNUAL": 4}
_DERIVATION_PATH = ("ytd_unaccumulation",)


@dataclass(frozen=True, slots=True)
class DerivationRefusal:
    """One cumulative span whose discrete quarter was not derived."""

    concept_qname: str
    unit: str | None
    dimensions: Mapping[str, str]
    start_date: str
    end_date: str
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "dimensions", MappingProxyType(dict(self.dimensions)))


@dataclass(frozen=True, slots=True)
class QuarterDerivation:
    """Derived discrete quarters plus every refused chain, with reasons."""

    derived: tuple[StitchedValue, ...]
    refusals: tuple[DerivationRefusal, ...]


def derive_discrete_quarters(
    series: StitchedSeries, item_types: Mapping[str, str] | None = None
) -> QuarterDerivation:
    """Derive the discrete quarters a stitched series does not report.

    Each derivation is one cumulative span minus the previous rung of
    the same chain; a span-average item type is refused, never differenced.
    """
    types = dict(item_types) if item_types is not None else {}
    groups: dict[tuple[object, ...], list[StitchedValue]] = {}
    for item in series.values:
        if item.period_type != "duration":
            continue
        key = (item.concept_qname, item.unit, tuple(sorted(item.dimensions.items())))
        groups.setdefault(key, []).append(item)
    derived: list[StitchedValue] = []
    refusals: list[DerivationRefusal] = []
    for members in groups.values():
        _derive_group(series, members, types, derived, refusals)
    derived.sort(key=_value_order)
    refusals.sort(key=lambda item: (item.concept_qname, item.start_date, item.end_date))
    return QuarterDerivation(derived=tuple(derived), refusals=tuple(refusals))


def _value_order(item: StitchedValue) -> tuple[object, ...]:
    return (
        item.concept_qname,
        item.end_date or "",
        item.start_date or "",
        item.unit or "",
        tuple(sorted(item.dimensions.items())),
    )


def _rung(item: StitchedValue) -> int | None:
    coordinate = normalize_time_coordinate(
        item.period_type, item.instant_date, item.start_date, item.end_date
    )
    return _RUNGS.get(coordinate.length_class)


def _refusal(target: StitchedValue, reason: str) -> DerivationRefusal:
    return DerivationRefusal(
        concept_qname=target.concept_qname,
        unit=target.unit,
        dimensions=target.dimensions,
        start_date=target.start_date or "",
        end_date=target.end_date or "",
        reason=reason,
    )


def _derive_group(
    series: StitchedSeries,
    members: list[StitchedValue],
    item_types: Mapping[str, str],
    derived: list[StitchedValue],
    refusals: list[DerivationRefusal],
) -> None:
    legs: dict[tuple[str, int], list[StitchedValue]] = {}
    reported_spans: set[tuple[str, str]] = set()
    for item in members:
        rung = _rung(item)
        if rung is None or not item.start_date:
            continue
        legs.setdefault((item.start_date, rung), []).append(item)
        if rung == 1 and item.end_date:
            reported_spans.add((item.start_date, item.end_date))
    for (start, rung), targets in sorted(legs.items()):
        if rung == 1:
            continue
        for target in targets:
            if len(targets) != 1:
                refusals.append(_refusal(target, AMBIGUOUS_LEG))
                continue
            outcome = _derive_one(
                series,
                target,
                legs.get((start, rung - 1)),
                reported_spans,
                item_types.get(target.concept_qname),
            )
            if isinstance(outcome, StitchedValue):
                derived.append(outcome)
            elif outcome is not None:
                refusals.append(outcome)


def _derive_one(
    series: StitchedSeries,
    target: StitchedValue,
    priors: list[StitchedValue] | None,
    reported_spans: set[tuple[str, str]],
    item_type: str | None,
) -> StitchedValue | DerivationRefusal | None:
    """One quarter from a cumulative span and its prior rung, or a refusal.

    None means the quarter is already reported for the derived span, so
    D5 leaves nothing to derive and nothing to refuse.
    """
    if priors is None:
        return _refusal(target, MISSING_PRIOR_LEG)
    if len(priors) != 1:
        return _refusal(target, AMBIGUOUS_LEG)
    prior = priors[0]
    if target.value is None or prior.value is None:
        return _refusal(target, LEG_WITHOUT_VALUE)
    if series.segment_of(prior) != series.segment_of(target):
        return _refusal(target, CROSSES_SERIES_BREAK)
    try:
        span_start = (
            date.fromisoformat(prior.end_date) + timedelta(days=1)
        ).isoformat()
    except (TypeError, ValueError):
        return _refusal(target, DERIVED_SPAN_NOT_QUARTER)
    if (span_start, target.end_date) in reported_spans:
        return None
    if is_non_additive_item_type(item_type):
        return _refusal(target, NON_ADDITIVE_ITEM_TYPE)
    coordinate = normalize_time_coordinate(
        "duration", None, span_start, target.end_date
    )
    if coordinate.length_class != "QUARTER":
        return _refusal(target, DERIVED_SPAN_NOT_QUARTER)
    return StitchedValue(
        concept_qname=target.concept_qname,
        period_type="duration",
        unit=target.unit,
        value=target.value - prior.value,
        status=QueryStatus.DERIVED,
        source_accession=target.source_accession,
        start_date=span_start,
        end_date=target.end_date,
        dimensions=target.dimensions,
        basis=DERIVED_EXACT_BASIS,
        derivation_path=_DERIVATION_PATH,
        derivation_inputs=(
            _input_of(prior),
            _input_of(target),
        ),
    )


def _input_of(item: StitchedValue) -> DerivationInput:
    """The derivation-input record naming one filed leg."""
    return DerivationInput(
        accession=item.source_accession,
        concept_qname=item.concept_qname,
        period_type=item.period_type,
        value=item.value,
        start_date=item.start_date,
        end_date=item.end_date,
        instant_date=item.instant_date,
    )
