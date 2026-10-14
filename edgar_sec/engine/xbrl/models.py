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
