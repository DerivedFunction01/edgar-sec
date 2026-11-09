"""Stitched financials: one filer's series values plus derived quarters.

Reported values come from the assembled series; derived discrete
quarters are added only where no reported quarter serves the span,
each carrying its derivation inputs.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from edgar_sec.engine.xbrl.solve.assembly import SeriesBreak, StitchedSeries
from edgar_sec.engine.xbrl.solve.stitched import StitchedValue
from edgar_sec.engine.xbrl.solve.unaccumulate import (
    DerivationRefusal,
    QuarterDerivation,
    derive_discrete_quarters,
)


@dataclass(frozen=True, slots=True)
class StitchedFinancials:
    """A stitched series with its derived quarters, at exact periods."""

    cik: str
    series: StitchedSeries
    derivation: QuarterDerivation

    @classmethod
    def from_series(
        cls, series: StitchedSeries, item_types: Mapping[str, str] | None = None
    ) -> "StitchedFinancials":
        """Wrap an assembled series, deriving the quarters it lacks."""
        return cls(
            cik=series.cik,
            series=series,
            derivation=derive_discrete_quarters(series, item_types),
        )

    @property
    def accessions(self) -> tuple[str, ...]:
        """The selected filing set, in filed order (result provenance)."""
        return self.series.accessions

    @property
    def superseded(self) -> tuple[StitchedValue, ...]:
        """Values a later filing replaced, each naming its superseder."""
        return self.series.superseded

    @property
    def breaks(self) -> tuple[SeriesBreak, ...]:
        """Fiscal-calendar breaks no stitch or derivation crosses."""
        return self.series.breaks

    @property
    def refusals(self) -> tuple[DerivationRefusal, ...]:
        """Cumulative spans whose quarter was not derived, with reasons."""
        return self.derivation.refusals

    def values(self, concept_qname: str | None = None) -> tuple[StitchedValue, ...]:
        """Winning reported values plus derived quarters, in period order."""
        pool = (*self.series.values, *self.derivation.derived)
        if concept_qname is not None:
            pool = tuple(item for item in pool if item.concept_qname == concept_qname)
        return tuple(sorted(pool, key=_value_order))

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
        """The value at one exact period key, or None on absence or ambiguity."""
        matches = [
            item
            for item in self.values()
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


def _value_order(item: StitchedValue) -> tuple[object, ...]:
    return (
        item.concept_qname,
        item.end_date or item.instant_date or "",
        item.start_date or "",
        item.unit or "",
        tuple(sorted(item.dimensions.items())),
    )


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
