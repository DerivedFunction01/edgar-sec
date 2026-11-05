"""Pooling support for the facade's equivalent-fact scan."""

from __future__ import annotations

from edgar_sec.apps.client.facts import XbrlFactSet
from edgar_sec.apps.client.fiscal import duration_length_class
from edgar_sec.engine.xbrl.schema.models import XbrlFact

_UNIT_EXCLUDED = ("pure", "shares", "item", "ratio")


def facts_by_head(fact_set: XbrlFactSet) -> dict[str | None, list[XbrlFact]]:
    """The fact set's facts grouped by the head their record's atom carries.

    Record-less facts group under None, which no atom head matches;
    each group preserves the fact set's own iteration order.
    """
    index: dict[str | None, list[XbrlFact]] = {}
    for fact in fact_set:
        record = fact_set.records.get(fact.concept_qname)
        head = record.atom.head if record is not None else None
        index.setdefault(head, []).append(fact)
    return index


def default_year_set(fact_set: XbrlFactSet, classes: frozenset[str]) -> frozenset[str]:
    """Year keys the equivalent scan's bucket creation spans, per class-set.

    Buckets are created ahead of the head and modifier filters, so
    the default year is population-wide, not head-local.
    """
    years: set[str] = set()
    for fact in fact_set:
        if fact.dimensions or not isinstance(fact.value, (int, float)):
            continue
        if fact.unit in _UNIT_EXCLUDED:
            continue
        if fact.start_date and fact.end_date:
            if duration_length_class(fact.start_date, fact.end_date) not in classes:
                continue
            years.add(fact.end_date[:4])
        elif fact.instant_date:
            years.add(fact.instant_date[:4])
    return frozenset(years)


def cached_default_years(
    cache: dict[frozenset[str], frozenset[str]],
    fact_set: XbrlFactSet,
    classes: frozenset[str],
) -> frozenset[str]:
    """The class-set's default-year set, computed once per cache."""
    years = cache.get(classes)
    if years is None:
        years = default_year_set(fact_set, classes)
        cache[classes] = years
    return years
