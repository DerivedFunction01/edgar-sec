"""Exact XBRL fact-context selection for queries and identity checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from edgar_sec.engine.xbrl.schema.models import XbrlFact


@dataclass(frozen=True, slots=True)
class FactScope:
    accession: str | None = None
    instant_date: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    unit: str | None = None
    dimensions: Mapping[str, str] = field(default_factory=dict)
    include_all_dimensions: bool = False

    def __post_init__(self) -> None:
        if self.start_date is not None and self.end_date is None:
            raise ValueError("duration scope requires both start_date and end_date")
        if self.end_date is not None and self.start_date is None:
            raise ValueError("duration scope requires both start_date and end_date")
        if self.instant_date and (self.start_date or self.end_date):
            raise ValueError("instant and duration dates are mutually exclusive")
        object.__setattr__(self, "dimensions", MappingProxyType(dict(self.dimensions)))

    def matches(self, fact: XbrlFact) -> bool:
        if self.accession and str(fact.accession) != self.accession:
            return False
        if self.instant_date is not None:
            if fact.period_type != "instant" or fact.instant_date != self.instant_date:
                return False
        elif self.start_date is not None:
            if (
                fact.period_type != "duration"
                or fact.start_date != self.start_date
                or fact.end_date != self.end_date
            ):
                return False
        if self.unit is not None and fact.unit != self.unit:
            return False
        if not self.include_all_dimensions and dict(fact.dimensions) != dict(
            self.dimensions
        ):
            return False
        return True

    def select(
        self, facts: tuple[XbrlFact, ...] | list[XbrlFact]
    ) -> tuple[XbrlFact, ...]:
        return tuple(fact for fact in facts if self.matches(fact))
