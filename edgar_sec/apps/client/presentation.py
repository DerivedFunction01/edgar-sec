"""Presentation statement views: display rows from a role's tree.

Rows follow the presentation arcs in filed order; values are the
filing's facts as filed, never recomputed. The calc graph stays the
algebraic view — this surface only displays.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from edgar_sec.apps.client.catalog import CatalogEntry
from edgar_sec.apps.client.display import filing_header
from edgar_sec.apps.client.facts import concept_display_name
from edgar_sec.apps.client.fiscal import duration_length_class
from edgar_sec.engine.xbrl.schema.models import PresentationArc, XbrlFact
from edgar_sec.engine.xbrl.solve.statement import period_rank

if TYPE_CHECKING:
    from edgar_sec.apps.client.kernel import FilingKernel

PRESENTATION_MODES = ("standard", "detailed", "summary")


@dataclass(frozen=True, slots=True)
class PresentationRow:
    """One display row: a tree occurrence, or one breakdown of it."""

    label: str
    concept: str
    depth: int
    abstract: bool
    dimensions: tuple[tuple[str, str], ...]
    values: dict[str, Any] = field(default_factory=dict)
    presentation_parent: str | None = None
    calculation_parent: str | None = None


class PresentationView:
    """A catalog role rendered as display rows in one dimensional mode."""

    def __init__(
        self,
        entry: CatalogEntry,
        mode: str,
        rows: tuple[PresentationRow, ...],
        periods: tuple[str, ...],
        labels: dict[str, str] | None = None,
        header: str | None = None,
    ) -> None:
        self.entry = entry
        self.mode = mode
        self.rows = rows
        self.periods = periods
        self.labels = dict(labels or {})
        self.header = header

    @property
    def title(self) -> str:
        """The catalog entry's humanized role title."""
        return self.entry.title

    @property
    def role_uri(self) -> str:
        """The presentation role these rows were built from."""
        return self.entry.role_uri

    def row(self, concept: str) -> PresentationRow | None:
        """Return the first face row for a concept, or None."""
        for row in self.rows:
            if row.concept == concept and not row.dimensions:
                return row
        return None

    def to_dataframe(self) -> Any:
        """Export rows to a DataFrame with period and dimension columns."""
        from edgar_sec.apps.client.rendering import presentation_to_dataframe

        return presentation_to_dataframe(self)

    def render_ascii(self, *, scaled: bool = True) -> str:
        """Render the rows as an ASCII statement table."""
        from edgar_sec.apps.client.rendering import render_presentation_ascii

        return render_presentation_ascii(self, scaled=scaled)

    def to_markdown(self, *, scaled: bool = True) -> str:
        """Render the rows as a markdown pipe table."""
        from edgar_sec.apps.client.markdown import presentation_to_markdown

        return presentation_to_markdown(self, scaled=scaled)

    def __str__(self) -> str:
        return self.render_ascii()

    def __repr__(self) -> str:
        return (
            f"<PresentationView title={self.title!r} mode={self.mode!r} "
            f"rows={len(self.rows)} periods={self.periods}>"
        )


def build_presentation_view(
    kernel: FilingKernel, entry: CatalogEntry, mode: str = "standard"
) -> PresentationView:
    """Build a role's display rows in the requested dimensional mode."""
    if mode not in PRESENTATION_MODES:
        raise ValueError(
            f"unknown presentation mode {mode!r}; expected one of {PRESENTATION_MODES}"
        )
    facts_by_concept: dict[str, list[XbrlFact]] = {}
    for fact in kernel.facts:
        facts_by_concept.setdefault(fact.concept_qname, []).append(fact)
    calc_parent = _calculation_parents(kernel, entry)
    in_role = set(entry.concepts)
    totals = {
        arc.parent_qname
        for arc in kernel.calculation_arcs
        if arc.parent_qname in in_role and arc.child_qname in in_role
    }
    children = _children_by_parent(entry.arcs)
    rows: list[PresentationRow] = []
    for root in entry.roots:
        _emit(
            kernel,
            entry,
            root,
            None,
            0,
            (),
            children,
            facts_by_concept,
            calc_parent,
            rows,
        )
    if mode == "standard":
        rows = [row for row in rows if not row.dimensions]
    elif mode == "summary":
        rows = [
            row
            for row in rows
            if not row.dimensions
            and (row.concept in totals or (row.depth == 0 and row.values))
        ]
    periods = tuple(sorted({period for row in rows for period in row.values}))
    header = filing_header(kernel.registrant_name, kernel.cik, kernel.accession)
    return PresentationView(
        entry, mode, tuple(rows), periods, kernel.labels, header=header
    )


def _emit(
    kernel: FilingKernel,
    entry: CatalogEntry,
    concept: str,
    parent: str | None,
    depth: int,
    path: tuple[str, ...],
    children: dict[str, list[PresentationArc]],
    facts_by_concept: dict[str, list[XbrlFact]],
    calc_parent: dict[str, str],
    rows: list[PresentationRow],
) -> None:
    if concept in path:
        return
    facts = facts_by_concept.get(concept, [])
    rows.append(
        PresentationRow(
            label=_concept_label(concept, kernel.labels),
            concept=concept,
            depth=depth,
            abstract=_is_abstract(kernel, concept, facts),
            dimensions=(),
            values=_values(fact for fact in facts if not fact.dimensions),
            presentation_parent=parent,
            calculation_parent=calc_parent.get(concept),
        )
    )
    for dimset in _breakdown_dimsets(entry, facts):
        rows.append(
            PresentationRow(
                label=_concept_label(concept, kernel.labels),
                concept=concept,
                depth=depth + 1,
                abstract=False,
                dimensions=dimset,
                values=_values(
                    fact
                    for fact in facts
                    if tuple(sorted(fact.dimensions.items())) == dimset
                ),
                presentation_parent=concept,
                calculation_parent=calc_parent.get(concept),
            )
        )
    for arc in children.get(concept, ()):
        _emit(
            kernel,
            entry,
            arc.child_qname,
            concept,
            depth + 1,
            (*path, concept),
            children,
            facts_by_concept,
            calc_parent,
            rows,
        )


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


def _breakdown_dimsets(
    entry: CatalogEntry, facts: list[XbrlFact]
) -> list[tuple[tuple[str, str], ...]]:
    """Distinct filed dimension sets on axes the role's own tree declares."""
    declared = set(entry.concepts)
    dimsets = {
        tuple(sorted(fact.dimensions.items()))
        for fact in facts
        if fact.dimensions
        and all(axis in declared for axis, _ in fact.dimensions.items())
    }
    return sorted(dimsets)


def _calculation_parents(kernel: FilingKernel, entry: CatalogEntry) -> dict[str, str]:
    """Displayed calc parent per concept: same-role arcs win, then any arc.

    Only arcs whose parent is itself in the role qualify, so the
    displayed parent is a row of the same statement.
    """
    in_role = set(entry.concepts)
    candidates: dict[str, list[tuple[bool, str]]] = {}
    for arc in kernel.calculation_arcs:
        if arc.child_qname in in_role and arc.parent_qname in in_role:
            candidates.setdefault(arc.child_qname, []).append(
                (arc.role_uri == entry.role_uri, arc.parent_qname)
            )
    return {
        child: sorted(options, reverse=True)[0][1]
        for child, options in candidates.items()
    }


def _is_abstract(kernel: FilingKernel, concept: str, facts: list[XbrlFact]) -> bool:
    """Declared abstract flag, else a fact-free tree node is a header."""
    declaration = kernel.declarations.get(concept)
    if declaration is not None:
        return declaration.abstract
    return not facts


def _period_key(fact: XbrlFact) -> str | None:
    """Period column key; a non-annual duration names its span class.

    Annual spans and instants keep the bare end/instant date, so a
    quarter and a year-to-date span ending the same day stay distinct.
    """
    if fact.period_type == "instant":
        return fact.instant_date
    if fact.end_date is None:
        return None
    if fact.start_date:
        cls = duration_length_class(fact.start_date, fact.end_date)
        if cls != "ANNUAL":
            return f"{fact.end_date} ({cls})"
    return fact.end_date


def period_key_class(period_key: str) -> str | None:
    """Span class a period key's suffix names, or None when unsuffixed."""
    _head, sep, tail = period_key.rpartition(" (")
    if sep and tail[-1:] == ")":
        return tail[:-1]
    return None


def _values(facts: Iterable[XbrlFact]) -> dict[str, Any]:
    """Period values from facts as filed; the best-ranked fact wins a cell."""
    best: dict[str, tuple[tuple[int, int], int, Any]] = {}
    for index, fact in enumerate(facts):
        period = _period_key(fact)
        if period is None:
            continue
        rank = period_rank(fact)
        current = best.get(period)
        if current is None or rank > current[0]:
            best[period] = (rank, index, fact.value)
    return {period: value for period, (_, _, value) in sorted(best.items())}


def _concept_label(concept: str, labels: dict[str, str]) -> str:
    """Filed label, else the local name split into words."""
    return concept_display_name(concept, labels)
