"""Strongly-typed data models for XBRL linkbase arcs, facts, and taxonomy frames."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from edgar_sec.domain.identity import AccessionNumber, Cik


@dataclass(frozen=True, slots=True)
class CalculationArc:
    """Directed edge in an XBRL calculation linkbase with summation weight."""

    parent_qname: str
    child_qname: str
    weight: float
    order: float | None = None
    role_uri: str | None = None


@dataclass(frozen=True, slots=True)
class PresentationArc:
    """Directed edge in an XBRL presentation linkbase with display order."""

    parent_qname: str
    child_qname: str
    order: float | None = None
    role_uri: str | None = None


@dataclass(frozen=True, slots=True)
class ConceptLabel:
    """Human-readable label for an XBRL concept."""

    concept_qname: str
    role_uri: str
    label: str
    lang: str = "en-US"


@dataclass(frozen=True, slots=True)
class ConceptDeclaration:
    """Extension schema taxonomy concept definition."""

    concept_qname: str
    name: str
    period_type: str | None = None
    balance: str | None = None
    substitution_group: str | None = None
    item_type: str | None = None


@dataclass(frozen=True, slots=True)
class XbrlFact:
    """Individual atomic or dimensional XBRL instance fact."""

    accession: AccessionNumber
    concept_qname: str
    value: float | str | None
    unit: str | None = None
    decimals: int | None = None
    period_type: str = "duration"
    start_date: str | None = None
    end_date: str | None = None
    instant_date: str | None = None
    dimensions: Mapping[str, str] = field(default_factory=dict)
    context_id: str | None = None
    balance: str | None = None


@dataclass(frozen=True, slots=True)
class LinkbaseBundle:
    """Aggregate collection of parsed linkbase arcs and labels."""

    calculation_arcs: tuple[CalculationArc, ...] = ()
    presentation_arcs: tuple[PresentationArc, ...] = ()
    labels: tuple[ConceptLabel, ...] = ()
    declarations: tuple[ConceptDeclaration, ...] = ()


@dataclass(frozen=True, slots=True)
class FilingXbrl:
    """Complete XBRL profile for a filing, uniting facts and linkbase graphs."""

    accession: AccessionNumber
    cik: Cik
    facts: tuple[XbrlFact, ...]
    linkbases: LinkbaseBundle


@dataclass(frozen=True, slots=True)
class GranularComponent:
    """Constituent component in a financial concept breakdown."""

    identifier: str
    value: float
    weight: float = 1.0
    member_dimension: str | None = None
    is_direct: bool = True


@dataclass(frozen=True, slots=True)
class ConceptBreakdown:
    """Granular breakdown of a financial concept into constituent parts."""

    target_concept: str
    total_value: float | None
    components: tuple[GranularComponent, ...]
    is_balanced: bool = True
    discrepancy: float = 0.0


@dataclass(frozen=True, slots=True)
class Verdict:
    """Three-valued classification of an XBRL fact within a target query domain."""

    concept_qname: str
    measure_id: str
    decision: str  # ACCEPT | REJECT | UNKNOWN
    role: str | None = None  # ROOT | SUBTOTAL | LEAF
    weight: float = 1.0
    reject_reason: str | None = None
    unknown_reason: str | None = (
        None  # UNSEEN_SIGNATURE | RESIDUAL_ONLY | LOW_SUPPORT | CONFLICT | NO_STRUCTURE
    )
    priority: float = 0.0


@dataclass(frozen=True, slots=True)
class AggregateFact:
    """Canonical aggregate financial fact with mathematical basis and provenance."""

    measure_id: str
    entity: str
    period: str
    unit: str
    value: float | None
    basis: str  # REPORTED_VERIFIED | REPORTED | DERIVED_EXACT | DERIVED_PARTIAL | CONFLICT | NOT_AVAILABLE
    slice_dimensions: Mapping[str, str] = field(default_factory=dict)
    components: tuple[GranularComponent, ...] = ()
    coverage: float = 1.0
    residual: float = 0.0
    derivation_path: tuple[str, ...] = ()
    confidence: float = 1.0
    breakdown: ConceptBreakdown | None = None
    resolution_tier: str = ""

    @property
    def target_concept(self) -> str:
        return self.measure_id

    @property
    def computed_value(self) -> float | None:
        return self.value

    @property
    def is_direct(self) -> bool:
        return self.basis in ("REPORTED", "REPORTED_VERIFIED")
