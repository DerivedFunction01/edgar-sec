"""Filing-location provenance: where a concept or fact sits in its filing.

Descriptive only: a location states what the substrate carries and
never feeds equivalence, candidacy, or query status.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from edgar_sec.apps.client.catalog import CatalogEntry
from edgar_sec.apps.client.facts import DisplayRecord, member_display_name
from edgar_sec.engine.xbrl.normalize.decomposer import split_camel_case
from edgar_sec.engine.xbrl.schema.models import (
    FilingXbrl,
    PresentationArc,
    XbrlFact,
    qname_local,
)

if TYPE_CHECKING:
    from edgar_sec.apps.client.kernel import FilingKernel

FIDELITY_INSTANCE = "instance"
FIDELITY_BUNDLE = "bundle"
FIDELITY_SNAPSHOT = "snapshot"
FIDELITY_LOOKUP = "lookup"


@dataclass(frozen=True, slots=True)
class PresentationPlacement:
    """One role whose tree contains the concept, with the path to it."""

    role_uri: str
    title: str
    category: str
    path: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CalculationParent:
    """One calculation arc summing the concept into a parent."""

    parent_qname: str
    weight: float
    role_uri: str | None


@dataclass(frozen=True, slots=True)
class FactContext:
    """The filed context of one specific fact, as the substrate carries it."""

    value: float | str | None
    period_type: str
    start_date: str | None
    end_date: str | None
    instant_date: str | None
    unit: str | None
    decimals: int | None
    context_id: str | None
    dimensions: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class FactLocation:
    """Where a concept sits: document, role paths, calc parents, context.

    Fidelity names the substrate: instance (live parse, document
    named), bundle, snapshot, or lookup (reduced projections).
    """

    qname: str
    label: str | None
    document: str | None
    accession: str
    cik: str
    fidelity: str
    placements: tuple[PresentationPlacement, ...]
    calculation_parents: tuple[CalculationParent, ...]
    fact: FactContext | None
    record: DisplayRecord | None


def build_location(
    kernel: FilingKernel,
    filing: FilingXbrl,
    entries: tuple[CatalogEntry, ...],
    qname: str,
    *,
    period: str | None = None,
    fact: XbrlFact | None = None,
    fidelity: str = FIDELITY_BUNDLE,
) -> FactLocation:
    """Assemble one concept's location, plus one fact's context block.

    Fact selection prefers the face fact (no dimensions) at the
    latest matching period; an explicit fact overrides selection.
    """
    selected = fact if fact is not None else _select_fact(kernel, qname, period)
    return FactLocation(
        qname=qname,
        label=kernel.labels.get(qname),
        document=filing.instance_document,
        accession=str(filing.accession),
        cik=str(filing.cik),
        fidelity=fidelity,
        placements=_placements(entries, qname),
        calculation_parents=_calculation_parents(kernel, qname),
        fact=fact_context(selected, kernel.labels) if selected is not None else None,
        record=kernel.records.get(qname),
    )


def fact_context(
    fact: XbrlFact, labels: Mapping[str, str] | None = None
) -> FactContext:
    """Context block for one fact: period, unit, decimals, dimensions."""
    return FactContext(
        value=fact.value,
        period_type=fact.period_type,
        start_date=fact.start_date,
        end_date=fact.end_date,
        instant_date=fact.instant_date,
        unit=fact.unit,
        decimals=fact.decimals,
        context_id=fact.context_id,
        dimensions=tuple(
            (_axis_display(axis, labels), member_display_name(member, labels))
            for axis, member in sorted(fact.dimensions.items())
        ),
    )


def _select_fact(
    kernel: FilingKernel, qname: str, period: str | None
) -> XbrlFact | None:
    candidates = [fact for fact in kernel.facts if fact.concept_qname == qname]
    if period is not None:
        candidates = [
            fact for fact in candidates if period in (fact.instant_date, fact.end_date)
        ]
    if not candidates:
        return None
    face = [fact for fact in candidates if not fact.dimensions]
    pool = face or candidates
    return max(pool, key=lambda fact: (_fact_date(fact), fact.context_id or ""))


def _fact_date(fact: XbrlFact) -> str:
    return fact.instant_date or fact.end_date or fact.start_date or ""


def _placements(
    entries: tuple[CatalogEntry, ...], qname: str
) -> tuple[PresentationPlacement, ...]:
    placements = []
    for entry in entries:
        if qname not in entry.concepts:
            continue
        path = _path_to(entry, qname)
        if path is None:
            continue
        placements.append(
            PresentationPlacement(
                role_uri=entry.role_uri,
                title=entry.title,
                category=entry.category,
                path=path,
            )
        )
    return tuple(placements)


def _path_to(entry: CatalogEntry, qname: str) -> tuple[str, ...] | None:
    children = _children_by_parent(entry.arcs)
    for root in entry.roots:
        found = _walk(root, qname, children, ())
        if found is not None:
            return found
    return None


def _walk(
    concept: str,
    target: str,
    children: dict[str, list[PresentationArc]],
    path: tuple[str, ...],
) -> tuple[str, ...] | None:
    if concept in path:
        return None
    path = (*path, concept)
    if concept == target:
        return path
    for arc in children.get(concept, ()):
        found = _walk(arc.child_qname, target, children, path)
        if found is not None:
            return found
    return None


def _children_by_parent(
    arcs: tuple[PresentationArc, ...],
) -> dict[str, list[PresentationArc]]:
    children: dict[str, list[PresentationArc]] = {}
    for arc in arcs:
        children.setdefault(arc.parent_qname, []).append(arc)
    for siblings in children.values():
        siblings.sort(
            key=lambda arc: (
                arc.order if arc.order is not None else 0.0,
                arc.child_qname,
            )
        )
    return children


def _calculation_parents(
    kernel: FilingKernel, qname: str
) -> tuple[CalculationParent, ...]:
    parents = {
        CalculationParent(arc.parent_qname, arc.weight, arc.role_uri)
        for arc in kernel.calculation_arcs
        if arc.child_qname == qname
    }
    return tuple(
        sorted(
            parents,
            key=lambda parent: (
                parent.parent_qname,
                parent.role_uri or "",
                parent.weight,
            ),
        )
    )


def _axis_display(axis: str, labels: Mapping[str, str] | None) -> str:
    """Filed axis label, else the axis local name split, minus Axis."""
    if labels:
        label = labels.get(axis)
        if label:
            return label
    tokens = list(split_camel_case(qname_local(axis)))
    if tokens and tokens[-1] == "Axis":
        tokens.pop()
    return " ".join(tokens) or axis
