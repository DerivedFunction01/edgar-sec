"""Fact cube coordinate normalization and dimensional categorization for XBRL facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping

from edgar_sec.engine.xbrl.domain import DomainTaxonomy, load_domain_taxonomy
from edgar_sec.engine.xbrl.models import XbrlFact


@dataclass(frozen=True, slots=True)
class TimeCoordinate:
    """Normalized temporal coordinates representing instant or duration length classes."""

    kind: str  # INSTANT | DURATION
    length_class: (
        str  # ANNUAL | QUARTER | YTD_2Q | YTD_3Q | CUMULATIVE | INSTANT | DURATION
    )
    date: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    days: int | None = None


@dataclass(frozen=True, slots=True)
class DimensionSlice:
    """Normalized dimensional coordinate classified into canonical axis family and member role."""

    axis_family: (
        str  # GEOGRAPHY | SEGMENT | PRODUCT_SERVICE | CUSTOMER | INSTRUMENT | OTHER
    )
    axis_qname: str
    member_qname: str
    member_role: str = "NORMAL"  # DEFAULT | NORMAL | TOTAL | RECONCILING


@dataclass(frozen=True, slots=True)
class NormalizedFact:
    """Fact cube coordinate representation with normalized temporal and slice projections."""

    raw_fact: XbrlFact
    measure_id: str
    entity: str
    time: TimeCoordinate
    unit_class: str
    canonical_value: float | None
    dimensions: tuple[DimensionSlice, ...] = ()

    @property
    def is_undimensioned(self) -> bool:
        """True if the fact has no non-default dimensional slices."""
        return not any(d.member_role != "DEFAULT" for d in self.dimensions)


def parse_iso_days(start_str: str, end_str: str) -> int | None:
    """Compute elapsed calendar days between two ISO-8601 date strings."""
    try:
        start_d = date.fromisoformat(start_str.strip())
        end_d = date.fromisoformat(end_str.strip())
        return (end_d - start_d).days
    except (ValueError, TypeError):
        return None


def normalize_time_coordinate(
    period_type: str,
    instant: str | None,
    start: str | None,
    end: str | None,
) -> TimeCoordinate:
    """Derive canonical time kind and length class from raw XBRL period timestamps."""
    p_lower = period_type.lower()
    if p_lower == "instant" or (instant and not start and not end):
        return TimeCoordinate(
            kind="INSTANT",
            length_class="INSTANT",
            date=instant or end or start,
        )

    if start and end:
        days = parse_iso_days(start, end)
        if days is not None:
            if 340 <= days <= 380:
                length_class = "ANNUAL"
            elif 75 <= days <= 105:
                length_class = "QUARTER"
            elif 160 <= days <= 200:
                length_class = "YTD_2Q"
            elif 250 <= days <= 295:
                length_class = "YTD_3Q"
            elif days > 380:
                length_class = "CUMULATIVE"
            else:
                length_class = "DURATION"
            return TimeCoordinate(
                kind="DURATION",
                length_class=length_class,
                start_date=start,
                end_date=end,
                date=end,
                days=days,
            )

    return TimeCoordinate(
        kind="DURATION",
        length_class="DURATION",
        start_date=start,
        end_date=end,
        date=end or instant,
    )


def classify_axis_family(
    axis_qname: str,
    taxonomy: DomainTaxonomy | None = None,
) -> str:
    """Classify an XBRL dimension axis QName using declarative taxonomy."""
    tax = taxonomy or load_domain_taxonomy()
    return tax.classify_axis(axis_qname)


def classify_member_role(member_qname: str) -> str:
    """Classify a dimension member QName into its accounting aggregation role."""
    local = member_qname.split(":")[-1].lower()
    if local.endswith("domain") or local.endswith("axis") or "default" in local:
        return "DEFAULT"
    if "total" in local:
        return "TOTAL"
    if any(k in local for k in ("elimination", "reconcil", "corporate", "other")):
        return "RECONCILING"
    return "NORMAL"


def normalize_unit_class(
    unit: str | None,
    taxonomy: DomainTaxonomy | None = None,
) -> str:
    """Normalize raw XBRL unit token using declarative taxonomy."""
    tax = taxonomy or load_domain_taxonomy()
    return tax.normalize_unit(unit)


def normalize_dimension_slices(
    dimensions: Mapping[str, str],
    taxonomy: DomainTaxonomy | None = None,
) -> tuple[DimensionSlice, ...]:
    """Convert raw dimension mapping into sorted canonical DimensionSlice tuples."""
    slices: list[DimensionSlice] = []
    for axis, member in sorted(dimensions.items()):
        slices.append(
            DimensionSlice(
                axis_family=classify_axis_family(axis, taxonomy),
                axis_qname=axis,
                member_qname=member,
                member_role=classify_member_role(member),
            )
        )
    return tuple(slices)


def normalize_fact(
    fact: XbrlFact,
    taxonomy: DomainTaxonomy | None = None,
) -> NormalizedFact:
    """Project an atomic XbrlFact into canonical coordinates on the multidimensional fact cube."""
    time_coord = normalize_time_coordinate(
        fact.period_type,
        fact.instant_date,
        fact.start_date,
        fact.end_date,
    )
    unit_coord = normalize_unit_class(fact.unit, taxonomy)
    dim_slices = normalize_dimension_slices(fact.dimensions, taxonomy)

    val: float | None = None
    if isinstance(fact.value, (int, float)):
        val = float(fact.value)
    elif isinstance(fact.value, str):
        try:
            val = float(fact.value)
        except ValueError:
            val = None

    measure_id = fact.concept_qname
    if taxonomy is not None:
        equivs = taxonomy.equivalent_concepts(measure_id)
        if equivs:
            measure_id = sorted(equivs, key=len)[0]

    return NormalizedFact(
        raw_fact=fact,
        measure_id=measure_id,
        entity=fact.accession.cik_prefix
        if hasattr(fact.accession, "cik_prefix")
        else str(fact.accession),
        time=time_coord,
        unit_class=unit_coord,
        canonical_value=val,
        dimensions=dim_slices,
    )
