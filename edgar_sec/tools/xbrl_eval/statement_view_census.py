"""Segment census for the statement-view driver."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from edgar_sec.apps.client.core.catalog import STATEMENT, CatalogEntry
from edgar_sec.apps.client.statements.presentation import declared_breakdown_members
from edgar_sec.tools.xbrl_eval.statement_view_cells import _guard

if TYPE_CHECKING:
    from edgar_sec.apps.client.xbrl import Xbrl


def _catalog_entries(xbrl: Xbrl) -> tuple[CatalogEntry, ...]:
    """Every catalog entry of the filing, resolved by role URI."""
    frame = xbrl.statements.list_available()
    entries: list[CatalogEntry] = []
    for role in frame["role"]:
        entry = xbrl.statements.get(str(role))
        if entry is not None:
            entries.append(entry)
    return tuple(entries)


def _filed_members(facts: Sequence[Any], graph: Any) -> frozenset[str]:
    """Distinct filed members in the group the served candidate came from."""
    return frozenset(
        fact.dimensions[graph.axis_qname]
        for fact in facts
        if fact.concept_qname == graph.concept_qname
        and len(fact.dimensions) == 1
        and graph.axis_qname in fact.dimensions
        and fact.unit == graph.unit
        and fact.start_date == graph.start_date
        and fact.end_date == graph.end_date
        and fact.instant_date == graph.instant_date
    )


def _segment_census(xbrl: Xbrl) -> list[dict[str, Any]]:
    """Per-(concept, axis) served candidates with their classifications."""
    facts = list(xbrl.facts)
    totals = {fact.concept_qname for fact in facts if not fact.dimensions}
    pairs = sorted(
        {
            (fact.concept_qname, axis)
            for fact in facts
            if len(fact.dimensions) == 1
            for axis in fact.dimensions
            if fact.concept_qname in totals
        }
    )
    records: list[dict[str, Any]] = []
    entries: tuple[CatalogEntry, ...] | None = None
    for concept, axis in pairs:
        view, error = _guard(
            lambda c=concept, a=axis: xbrl.financials.segment_breakdown(
                concept_qname=c, axis_qname=a
            )
        )
        if error is not None:
            records.append({"concept": concept, "axis": axis, "error": error})
            continue
        graph = view.graph
        record = graph.classification
        if graph.total is None or record is None:
            continue
        census: dict[str, Any] = {
            "concept": concept,
            "axis": axis,
            "unit": graph.unit,
            "members_filed": len(_filed_members(facts, graph)),
            "members_served": len(graph.members),
            "total": graph.total,
            "filed_member_sum": graph.filed_member_sum,
            "sum_ratio": (
                None
                if not graph.total or graph.filed_member_sum is None
                else graph.filed_member_sum / graph.total
            ),
            "class": record.kind,
            "basis": record.basis,
            "capped": record.enumeration_capped,
            "partitions": [list(part) for part in record.partitions],
            "subsumed": list(record.subsumed),
        }
        if record.kind == "overlapping_partitions":
            if entries is None:
                entries = _catalog_entries(xbrl)
            declared = declared_breakdown_members(
                entries, concept, axis, _filed_members(facts, graph)
            )
            partition_sets = [frozenset(part) for part in record.partitions]
            census["declared"] = sum(
                1
                for part in partition_sets
                if any(part == members for _category, members in declared)
            )
            census["statement_declared"] = sum(
                1
                for part in partition_sets
                if any(
                    part == members
                    for category, members in declared
                    if category == STATEMENT
                )
            )
        records.append(census)
    return records
