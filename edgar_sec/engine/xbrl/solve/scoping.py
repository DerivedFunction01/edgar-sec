"""Exact XBRL fact-context selection for queries and identity checks."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from edgar_sec.engine.xbrl.schema.models import XbrlFact

_AMENDMENT_SUFFIX = "/A"


def base_form(form: str) -> str:
    """A form code's base form: the amendment suffix removed."""
    return form.removesuffix(_AMENDMENT_SUFFIX)


def is_amendment_form(form: str) -> bool:
    """True when a form code amends its base form."""
    return form != base_form(form)


@dataclass(frozen=True, slots=True)
class FilingRef:
    """One filing's lineage coordinates, from submissions metadata."""

    accession: str
    cik: str
    form: str
    report_period: str
    filed_date: str = ""


@dataclass(frozen=True, slots=True)
class AmendmentLineage:
    """An original filing and its amendments, in supersession order."""

    cik: str
    form: str
    report_period: str
    accessions: tuple[str, ...]

    @property
    def original(self) -> str:
        """The lineage's original (unamended) accession."""
        return self.accessions[0]

    @property
    def latest(self) -> str:
        """The lineage's latest accession: the restated population."""
        return self.accessions[-1]

    def rank(self, accession: str) -> int | None:
        """Supersession rank of an accession in this lineage, if carried."""
        try:
            return self.accessions.index(accession)
        except ValueError:
            return None


def build_lineages(refs: Iterable[FilingRef]) -> tuple[AmendmentLineage, ...]:
    """Group filing refs into amendment lineages by (cik, base form, period).

    Keys come from submissions metadata; the filed dei amendment flag is
    never consulted. Groups carrying no amendment are not lineages.
    """
    groups: dict[tuple[str, str, str], list[FilingRef]] = {}
    for ref in refs:
        key = (ref.cik, base_form(ref.form), ref.report_period)
        groups.setdefault(key, []).append(ref)
    lineages = []
    for (cik, form, period), members in sorted(groups.items()):
        if not any(is_amendment_form(member.form) for member in members):
            continue
        ordered = sorted(
            members,
            key=lambda m: (is_amendment_form(m.form), m.filed_date, m.accession),
        )
        lineages.append(
            AmendmentLineage(
                cik=cik,
                form=form,
                report_period=period,
                accessions=tuple(member.accession for member in ordered),
            )
        )
    return tuple(lineages)


def covering_lineage(
    lineages: Iterable[AmendmentLineage], accessions: Iterable[str]
) -> AmendmentLineage | None:
    """The one lineage covering every accession, or None."""
    wanted = set(accessions)
    matches = [lineage for lineage in lineages if wanted & set(lineage.accessions)]
    if len(matches) != 1 or not wanted <= set(matches[0].accessions):
        return None
    return matches[0]


def fact_key(fact: XbrlFact) -> tuple[object, ...]:
    """A fact's supersession key: concept, period, and dimensions."""
    return (
        fact.concept_qname,
        fact.period_type,
        fact.start_date,
        fact.end_date,
        fact.instant_date,
        tuple(sorted(fact.dimensions.items())),
    )


def supersede_facts(
    facts: Iterable[XbrlFact],
    lineages: Iterable[AmendmentLineage],
) -> tuple[XbrlFact, ...]:
    """Resolve a pooled population over amendment lineages.

    A fact survives only when no later filing carries its key: restated
    keys answer from the amendment, non-overlapping original facts stand.
    """
    return tuple(
        item.fact
        for item in supersede_facts_retained(facts, lineages)
        if item.superseded_by is None
    )


@dataclass(frozen=True, slots=True)
class ResolvedFact:
    """One pooled fact; superseded_by names its replacement, when one won."""

    fact: XbrlFact
    superseded_by: str | None = None


def supersede_facts_retained(
    facts: Iterable[XbrlFact],
    lineages: Iterable[AmendmentLineage],
) -> tuple[ResolvedFact, ...]:
    """Lineage supersession with the losers retained, pool order preserved.

    A loser names the accession whose fact won its key; same-accession
    duplicates share the winning rank and are never superseded.
    """
    ranks: dict[str, tuple[int, int]] = {}
    for group, lineage in enumerate(lineages):
        for rank, accession in enumerate(lineage.accessions):
            ranks[accession] = (group, rank)
    pool = list(facts)
    best: dict[tuple[object, ...], tuple[int, str]] = {}
    for fact in pool:
        found = ranks.get(str(fact.accession))
        if found is None:
            continue
        key = (found[0], fact_key(fact))
        current = best.get(key)
        if current is None or found[1] > current[0]:
            best[key] = (found[1], str(fact.accession))
    resolved = []
    for fact in pool:
        found = ranks.get(str(fact.accession))
        if found is None:
            resolved.append(ResolvedFact(fact))
            continue
        rank, winner = best[(found[0], fact_key(fact))]
        if found[1] == rank:
            resolved.append(ResolvedFact(fact))
        else:
            resolved.append(ResolvedFact(fact, superseded_by=winner))
    return tuple(resolved)


def _precedence_rank(ref: FilingRef) -> tuple[str, bool, str]:
    """Cross-filing precedence of one filing: filed date, form, accession."""
    return (ref.filed_date, is_amendment_form(ref.form), ref.accession)


def resolve_precedence(
    facts: Iterable[XbrlFact],
    refs: Iterable[FilingRef],
    lineages: Iterable[AmendmentLineage] = (),
) -> tuple[ResolvedFact, ...]:
    """Latest-filed-wins precedence over a pooled cross-filing population.

    Lineage supersession runs first, unchanged; ties break by the
    base-form rule then accession, and same-vintage duplicates stay.
    """
    ranks = {ref.accession: _precedence_rank(ref) for ref in refs}

    def rank_of(accession: str) -> tuple[str, bool, str]:
        return ranks.get(accession, ("", False, accession))

    resolved = supersede_facts_retained(facts, lineages)
    best: dict[tuple[object, ...], tuple[tuple[str, bool, str], str]] = {}
    for item in resolved:
        if item.superseded_by is not None:
            continue
        accession = str(item.fact.accession)
        rank = rank_of(accession)
        key = fact_key(item.fact)
        current = best.get(key)
        if current is None or rank > current[0]:
            best[key] = (rank, accession)
    out = []
    for item in resolved:
        if item.superseded_by is not None:
            out.append(item)
            continue
        accession = str(item.fact.accession)
        _, winner = best[fact_key(item.fact)]
        if winner == accession:
            out.append(item)
        else:
            out.append(ResolvedFact(item.fact, superseded_by=winner))
    return tuple(out)


@dataclass(frozen=True, slots=True)
class FactScope:
    accession: str | None = None
    instant_date: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    unit: str | None = None
    dimensions: Mapping[str, str] = field(default_factory=dict)
    include_all_dimensions: bool = False
    lineages: tuple[AmendmentLineage, ...] = ()

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
        selected = [fact for fact in facts if self.matches(fact)]
        if self.lineages:
            return supersede_facts(selected, self.lineages)
        return tuple(selected)
