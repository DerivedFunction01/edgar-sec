"""Cross-filing assembly: one filer's pooled facts as a stitched series.

Precedence is resolve_precedence over the selected set; fiscal-calendar
breaks split the series into segments instead of joining across them.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta

from edgar_sec.domain.forms.common.aliases import is_transition_form
from edgar_sec.engine.xbrl.normalize.filed_metadata import filed_metadata
from edgar_sec.engine.xbrl.normalize.normalization import normalize_time_coordinate
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.solve.scoping import (
    FilingRef,
    build_lineages,
    resolve_precedence,
)
from edgar_sec.engine.xbrl.solve.stitched import StitchedValue

TRANSITION_REASON = "transition_period"
FYE_CHANGE_REASON = "fiscal_year_end_change"
_MONTH_DAY_TOLERANCE = 10


@dataclass(frozen=True, slots=True)
class SeriesBreak:
    """A fiscal-calendar break: no stitching crosses it.

    after_end is the last period end on the earlier calendar; a value
    belongs to the later segment when its period end is after it.
    """

    after_end: str
    reason: str
    transition_start: str | None = None
    transition_end: str | None = None


@dataclass(frozen=True, slots=True)
class StitchedSeries:
    """One filer's stitched values over a recorded filing set."""

    cik: str
    refs: tuple[FilingRef, ...]
    values: tuple[StitchedValue, ...]
    superseded: tuple[StitchedValue, ...]
    breaks: tuple[SeriesBreak, ...]

    @property
    def accessions(self) -> tuple[str, ...]:
        """The selected filing set, in filed order."""
        return tuple(ref.accession for ref in self.refs)

    @property
    def segment_count(self) -> int:
        """Number of calendar segments the breaks split the series into."""
        return len(self.breaks) + 1

    def value(
        self,
        concept_qname: str,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        instant_date: str | None = None,
        unit: str | None = None,
        dimensions: Mapping[str, str] | None = None,
    ) -> StitchedValue | None:
        """The winning value at one exact period key, or None.

        Absence is honest: an unreported period, or a key two units
        carry, answers None rather than a silently picked value.
        """
        matches = [
            item
            for item in self.values
            if _key_matches(
                item,
                concept_qname,
                start_date,
                end_date,
                instant_date,
                unit,
                dimensions,
            )
        ]
        return matches[0] if len(matches) == 1 else None

    def values_for(self, concept_qname: str) -> tuple[StitchedValue, ...]:
        """Winning values for one concept, in period order."""
        return tuple(
            item for item in self.values if item.concept_qname == concept_qname
        )

    def segment_of(self, value: StitchedValue) -> int:
        """The calendar segment a value falls in, by its period end."""
        end = value.end_date or value.instant_date or ""
        return sum(1 for item in self.breaks if item.after_end < end)

    def segment(self, index: int) -> tuple[StitchedValue, ...]:
        """Winning values in one calendar segment, in series order."""
        return tuple(item for item in self.values if self.segment_of(item) == index)


def _key_matches(
    item: StitchedValue,
    concept_qname: str,
    start_date: str | None,
    end_date: str | None,
    instant_date: str | None,
    unit: str | None,
    dimensions: Mapping[str, str] | None,
) -> bool:
    if item.concept_qname != concept_qname:
        return False
    if instant_date is not None:
        if item.period_type != "instant" or item.instant_date != instant_date:
            return False
    elif (
        item.period_type != "duration"
        or item.start_date != start_date
        or item.end_date != end_date
    ):
        return False
    if unit is not None and item.unit != unit:
        return False
    if dimensions is None:
        return not item.dimensions
    return dict(item.dimensions) == dict(dimensions)


def _value_order(item: StitchedValue) -> tuple[object, ...]:
    return (
        item.concept_qname,
        item.end_date or item.instant_date or "",
        item.start_date or "",
        item.unit or "",
        tuple(sorted(item.dimensions.items())),
    )


def assemble_series(
    cik: str,
    facts: Iterable[XbrlFact],
    refs: Iterable[FilingRef],
) -> StitchedSeries:
    """Assemble one filer's stitched series over a selected filing set.

    Only facts filed under a selected accession enter, and only numeric
    facts become values; the set is recorded on the series as provenance.
    """
    ref_tuple = tuple(sorted(refs, key=lambda ref: (ref.filed_date, ref.accession)))
    selected = {ref.accession for ref in ref_tuple}
    pool = [
        fact
        for fact in facts
        if str(fact.accession) in selected and isinstance(fact.value, (int, float))
    ]
    resolved = resolve_precedence(pool, ref_tuple, build_lineages(ref_tuple))
    values: list[StitchedValue] = []
    superseded: list[StitchedValue] = []
    for item in resolved:
        value = StitchedValue.from_fact(item.fact)
        if item.superseded_by is None:
            values.append(value)
        else:
            superseded.append(value.superseded(item.superseded_by))
    by_accession: dict[str, list[XbrlFact]] = {}
    for fact in pool:
        by_accession.setdefault(str(fact.accession), []).append(fact)
    breaks = _merge_breaks(
        [
            *_transition_breaks(
                by_accession, {ref.accession: ref for ref in ref_tuple}
            ),
            *_fye_change_breaks(pool),
        ]
    )
    return StitchedSeries(
        cik=cik,
        refs=ref_tuple,
        values=tuple(sorted(values, key=_value_order)),
        superseded=tuple(sorted(superseded, key=_value_order)),
        breaks=breaks,
    )


def _merge_breaks(candidates: list[SeriesBreak]) -> tuple[SeriesBreak, ...]:
    """One break per boundary date; a transition break wins its boundary."""
    by_end: dict[str, SeriesBreak] = {}
    for item in candidates:
        current = by_end.get(item.after_end)
        if current is None or (
            current.reason != TRANSITION_REASON and item.reason == TRANSITION_REASON
        ):
            by_end[item.after_end] = item
    return tuple(by_end[end] for end in sorted(by_end))


def _is_annual(fact: XbrlFact) -> bool:
    if fact.dimensions or fact.period_type != "duration":
        return False
    if not fact.start_date or not fact.end_date:
        return False
    coordinate = normalize_time_coordinate(
        fact.period_type, fact.instant_date, fact.start_date, fact.end_date
    )
    return coordinate.length_class == "ANNUAL"


def _fye_change_breaks(pool: list[XbrlFact]) -> list[SeriesBreak]:
    """Breaks where consecutive annual period ends change month-day.

    A 52/53-week calendar wobbles its year end by days only; a change
    beyond the tolerance is a new fiscal calendar, not a wobble.
    """
    ends = sorted(
        {fact.end_date for fact in pool if _is_annual(fact) and fact.end_date}
    )
    breaks = []
    for earlier, later in zip(ends, ends[1:]):
        try:
            first = date.fromisoformat(earlier)
            second = date.fromisoformat(later)
        except ValueError:
            continue
        distance = _month_day_distance(
            (first.month, first.day), (second.month, second.day)
        )
        if distance > _MONTH_DAY_TOLERANCE:
            breaks.append(SeriesBreak(after_end=earlier, reason=FYE_CHANGE_REASON))
    return breaks


def _month_day_distance(a: tuple[int, int], b: tuple[int, int]) -> int:
    """Circular distance in days between two month-days, within 0..182."""

    def ordinal(month_day: tuple[int, int]) -> int:
        month, day = month_day
        return (
            date(2001, month, min(day, 28) if month == 2 else day).timetuple().tm_yday
        )

    diff = abs(ordinal(a) - ordinal(b))
    return min(diff, 365 - diff)


def _transition_breaks(
    by_accession: dict[str, list[XbrlFact]],
    refs: dict[str, FilingRef],
) -> list[SeriesBreak]:
    """Breaks at transition filings: the stub span opens the new calendar."""
    breaks = []
    for accession, facts in by_accession.items():
        ref = refs.get(accession)
        metadata = filed_metadata(facts)
        is_transition = (
            (ref is not None and is_transition_form(ref.form))
            or metadata.transition_report is True
            or is_transition_form(metadata.document_type)
        )
        if not is_transition:
            continue
        stub = _stub_span(facts, metadata.period_end)
        if stub is None:
            continue
        start, end = stub
        try:
            after_end = (date.fromisoformat(start) - timedelta(days=1)).isoformat()
        except ValueError:
            continue
        breaks.append(
            SeriesBreak(
                after_end=after_end,
                reason=TRANSITION_REASON,
                transition_start=start,
                transition_end=end,
            )
        )
    return breaks


def _stub_span(facts: list[XbrlFact], period_end: str | None) -> tuple[str, str] | None:
    """A transition filing's stub: its most-carried undimensioned duration.

    Mirrors the client fiscal rule; spans ending at the filed period
    end are preferred, then the longest span.
    """
    counts: Counter[tuple[str, str]] = Counter()
    for fact in facts:
        if fact.dimensions or fact.period_type != "duration":
            continue
        if not fact.start_date or not fact.end_date:
            continue
        counts[(fact.start_date, fact.end_date)] += 1
    if not counts:
        return None
    at_end = [span for span in counts if span[1] == period_end]
    pool = at_end or list(counts)
    return max(pool, key=lambda span: (counts[span], _span_days(span), span))


def _span_days(span: tuple[str, str]) -> int:
    try:
        return (date.fromisoformat(span[1]) - date.fromisoformat(span[0])).days
    except ValueError:
        return -1
