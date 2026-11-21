"""Placement facts: span construction and per-table facts.
Definitions mirror the priced Step 1 placement lane exactly:
first primary run, gap tolerance two, deep notes at fifteen."""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.core import placement, registry
from edgar_sec.engine.tables.extraction.core.placement import (
    REGION_FRONT,
    REGION_NOTES,
    REGION_STATEMENTS,
    REGION_UNKNOWN,
    placement_facts,
    statement_span,
)


def test_placement_consumes_the_registry_primary_set(monkeypatch) -> None:
    # The binding is the registry's own object, not a local copy:
    # shrinking the registry set moves the span placement builds.
    assert placement.PRIMARY_STATEMENT_FAMILIES is (registry.PRIMARY_STATEMENT_FAMILIES)
    reduced = tuple(
        family
        for family in registry.PRIMARY_STATEMENT_FAMILIES
        if family != "cash_flow"
    )
    monkeypatch.setattr(placement, "PRIMARY_STATEMENT_FAMILIES", reduced)
    families = ("balance_sheet", "other", "cash_flow")
    assert statement_span(families) == (0, 0)


def test_span_opens_at_first_primary_and_tolerates_gaps() -> None:
    families = ("other", "balance_sheet", "other", "other", "cash_flow", "other")
    assert statement_span(families) == (1, 4)


def test_span_breaks_at_a_gap_over_tolerance() -> None:
    families = ("balance_sheet", "other", "other", "other", "cash_flow")
    assert statement_span(families) == (0, 0)


def test_no_primary_no_span() -> None:
    assert statement_span(("other", "ppe", "other")) is None
    facts = placement_facts(("other", "ppe", "other"), 1)
    assert facts.region == REGION_UNKNOWN
    assert facts.no_statement_cluster
    assert not facts.deep_notes


def test_regions_and_distances() -> None:
    families = ("other", "balance_sheet", "cash_flow") + ("other",) * 16
    front = placement_facts(families, 0)
    assert front.region == REGION_FRONT and front.span_distance == -1
    inside = placement_facts(families, 2)
    assert inside.region == REGION_STATEMENTS and inside.in_span
    near = placement_facts(families, 5)
    assert near.region == REGION_NOTES and not near.deep_notes
    deep = placement_facts(families, 17)
    assert deep.region == REGION_NOTES and deep.deep_notes
    assert deep.span_distance == 15


def test_isolation_counts_primary_neighbours_within_two() -> None:
    families = ("balance_sheet",) + ("other",) * 6 + ("ppe",)
    assert not placement_facts(families, 2).isolated
    assert placement_facts(families, 3).isolated
    assert placement_facts(families, 7).isolated
