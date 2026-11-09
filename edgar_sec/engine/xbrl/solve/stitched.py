"""Period-keyed stitched values: one filer's value with its provenance.

Identity is the exact period, concept, unit, and dimensions — never a
year string; provenance is the filing accession, the superseding
accession where one exists, and the derivation inputs where derived.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Mapping

from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.solve.query import QueryStatus

REPORTED_BASIS = "REPORTED"
DERIVED_EXACT_BASIS = "DERIVED_EXACT"
DERIVED_PARTIAL_BASIS = "DERIVED_PARTIAL"


@dataclass(frozen=True, slots=True)
class DerivationInput:
    """One filed value a derived stitched value was computed from."""

    accession: str
    concept_qname: str
    period_type: str
    value: float | None = None
    start_date: str | None = None
    end_date: str | None = None
    instant_date: str | None = None

    @classmethod
    def from_fact(cls, fact: XbrlFact) -> "DerivationInput":
        """The input reference for one source fact."""
        return cls(
            accession=str(fact.accession),
            concept_qname=fact.concept_qname,
            period_type=fact.period_type,
            value=float(fact.value) if isinstance(fact.value, (int, float)) else None,
            start_date=fact.start_date,
            end_date=fact.end_date,
            instant_date=fact.instant_date,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "accession": self.accession,
            "concept_qname": self.concept_qname,
            "period_type": self.period_type,
            "value": self.value,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "instant_date": self.instant_date,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DerivationInput":
        """Rebuild from :meth:`to_dict` output."""
        return cls(
            accession=str(data["accession"]),
            concept_qname=str(data["concept_qname"]),
            period_type=str(data["period_type"]),
            value=data.get("value"),
            start_date=data.get("start_date"),
            end_date=data.get("end_date"),
            instant_date=data.get("instant_date"),
        )


@dataclass(frozen=True, slots=True)
class StitchedValue:
    """One period-keyed value in a filer's stitched series."""

    concept_qname: str
    period_type: str
    unit: str | None
    value: float | None
    status: QueryStatus
    source_accession: str
    start_date: str | None = None
    end_date: str | None = None
    instant_date: str | None = None
    dimensions: Mapping[str, str] = field(default_factory=dict)
    basis: str = REPORTED_BASIS
    derivation_path: tuple[str, ...] = ()
    derivation_inputs: tuple[DerivationInput, ...] = ()
    superseded_by: str | None = None

    def __post_init__(self) -> None:
        if self.period_type == "duration":
            if not self.start_date or not self.end_date or self.instant_date:
                raise ValueError("duration values require start and end dates only")
        elif self.period_type == "instant":
            if not self.instant_date or self.start_date or self.end_date:
                raise ValueError("instant values require an instant date only")
        else:
            raise ValueError(f"unknown period_type: {self.period_type!r}")
        if self.status == QueryStatus.DERIVED and not self.derivation_inputs:
            raise ValueError("a DERIVED value must name its derivation inputs")
        if (
            self.superseded_by is not None
            and self.superseded_by == self.source_accession
        ):
            raise ValueError("a value cannot be superseded by its own accession")
        object.__setattr__(self, "dimensions", MappingProxyType(dict(self.dimensions)))
        object.__setattr__(self, "derivation_path", tuple(self.derivation_path))
        object.__setattr__(self, "derivation_inputs", tuple(self.derivation_inputs))

    @property
    def key(self) -> tuple[object, ...]:
        """Identity: concept, exact period, unit, and dimensions."""
        return (
            self.concept_qname,
            self.period_type,
            self.start_date,
            self.end_date,
            self.instant_date,
            self.unit,
            tuple(sorted(self.dimensions.items())),
        )

    @property
    def period_key(self) -> tuple[object, ...]:
        """The exact period alone: (start, end) or the instant."""
        return (
            self.period_type,
            self.start_date,
            self.end_date,
            self.instant_date,
        )

    @property
    def is_superseded(self) -> bool:
        """True when a later filing's value replaced this one."""
        return self.superseded_by is not None

    def superseded(self, by_accession: str) -> "StitchedValue":
        """A copy of this value marked superseded by another accession."""
        return replace(self, superseded_by=by_accession)

    @classmethod
    def from_fact(
        cls,
        fact: XbrlFact,
        *,
        status: QueryStatus = QueryStatus.REPORTED,
        basis: str = REPORTED_BASIS,
    ) -> "StitchedValue":
        """The stitched value a numeric filed fact represents."""
        if not isinstance(fact.value, (int, float)):
            raise ValueError("stitched values are numeric; the fact is not")
        return cls(
            concept_qname=fact.concept_qname,
            period_type=fact.period_type,
            unit=fact.unit,
            value=float(fact.value),
            status=status,
            source_accession=str(fact.accession),
            start_date=fact.start_date,
            end_date=fact.end_date,
            instant_date=fact.instant_date,
            dimensions=fact.dimensions,
            basis=basis,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "concept_qname": self.concept_qname,
            "period_type": self.period_type,
            "unit": self.unit,
            "value": self.value,
            "status": str(self.status),
            "source_accession": self.source_accession,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "instant_date": self.instant_date,
            "dimensions": dict(sorted(self.dimensions.items())),
            "basis": self.basis,
            "derivation_path": list(self.derivation_path),
            "derivation_inputs": [item.to_dict() for item in self.derivation_inputs],
            "superseded_by": self.superseded_by,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StitchedValue":
        """Rebuild from :meth:`to_dict` output."""
        return cls(
            concept_qname=str(data["concept_qname"]),
            period_type=str(data["period_type"]),
            unit=data.get("unit"),
            value=data.get("value"),
            status=QueryStatus(str(data["status"])),
            source_accession=str(data["source_accession"]),
            start_date=data.get("start_date"),
            end_date=data.get("end_date"),
            instant_date=data.get("instant_date"),
            dimensions=dict(data.get("dimensions") or {}),
            basis=str(data.get("basis") or REPORTED_BASIS),
            derivation_path=tuple(data.get("derivation_path") or ()),
            derivation_inputs=tuple(
                DerivationInput.from_dict(item)
                for item in data.get("derivation_inputs") or ()
            ),
            superseded_by=data.get("superseded_by"),
        )
