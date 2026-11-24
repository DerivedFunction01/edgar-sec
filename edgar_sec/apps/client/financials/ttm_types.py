"""Leg and result types for TTM derivation.

A TTM answer is a statused result over span legs; the leg set pairs
reported spans with the discrete quarters derived from them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from edgar_sec.engine.xbrl.solve.core.query import QueryStatus


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
