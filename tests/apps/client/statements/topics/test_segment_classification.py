from __future__ import annotations

from edgar_sec.apps.client.core.catalog import DISCLOSURE, STATEMENT, CatalogEntry
from edgar_sec.engine.xbrl.schema.models import PresentationArc, XbrlFact
from tests.apps.client.statements.topics.topic_fixtures import (
    _BIZ_AXIS,
    _REV,
    _build_segments,
    _def_arcs,
    _segment_fact,
)


def test_segment_breakdown_excludes_subsumed_members_from_arcs() -> None:
    """An aggregate member replaces its subsumed members declaratively."""
    facts = [
        _segment_fact(_REV, 1000.0),
        _segment_fact(_REV, 1000.0, {_BIZ_AXIS: "x:AllMember"}),
        _segment_fact(_REV, 600.0, {_BIZ_AXIS: "x:AlphaMember"}),
        _segment_fact(_REV, 400.0, {_BIZ_AXIS: "x:BetaMember"}),
    ]
    arcs = _def_arcs(
        _BIZ_AXIS,
        "x:SegmentDomain",
        [
            ("x:SegmentDomain", "x:AllMember"),
            ("x:AllMember", "x:AlphaMember"),
            ("x:AllMember", "x:BetaMember"),
        ],
    )
    graph = _build_segments(
        facts, concept_qname=_REV, axis_qname=_BIZ_AXIS, definition_arcs=arcs
    )
    assert {m.member_qname: m.value for m in graph.members} == {"x:AllMember": 1000.0}
    assert graph.verified is True
    # Arcless, the same facts are two disjoint partitions (the aggregate
    # alone, or its two components); the finest serves, verified.
    fallback = _build_segments(facts, concept_qname=_REV, axis_qname=_BIZ_AXIS)
    assert {m.member_qname for m in fallback.members} == {
        "x:AlphaMember",
        "x:BetaMember",
    }
    assert fallback.verified is True
    assert fallback.classification is not None
    assert fallback.classification.kind == "overlapping_partitions"


def test_segment_breakdown_classifies_flat_overlap() -> None:
    """Two disjoint complete partitions classify as overlapping."""
    facts = [
        _segment_fact(_REV, 1000.0),
        _segment_fact(_REV, 450.0, {_BIZ_AXIS: "x:ProductMember"}),
        _segment_fact(_REV, 550.0, {_BIZ_AXIS: "x:ServiceOtherMember"}),
    ]
    facts.extend(
        _segment_fact(_REV, 100.0, {_BIZ_AXIS: f"x:Detail{i}Member"}) for i in range(10)
    )
    graph = _build_segments(facts, concept_qname=_REV, axis_qname=_BIZ_AXIS)
    assert graph.classification is not None
    assert graph.classification.kind == "overlapping_partitions"
    assert graph.classification.partitions == (
        tuple(f"x:Detail{i}Member" for i in range(10)),
        ("x:ProductMember", "x:ServiceOtherMember"),
    )
    assert graph.filed_member_sum == 2000.0
    # Undeclared, the finest partition serves (the ten details).
    assert len(graph.members) == 10
    assert graph.verified is True


def test_segment_breakdown_classifies_nested_from_arcs() -> None:
    """Arc-subsumed members classify nested while the aggregate serves."""
    facts = [
        _segment_fact(_REV, 1000.0),
        _segment_fact(_REV, 1000.0, {_BIZ_AXIS: "x:AllMember"}),
        _segment_fact(_REV, 600.0, {_BIZ_AXIS: "x:AlphaMember"}),
        _segment_fact(_REV, 400.0, {_BIZ_AXIS: "x:BetaMember"}),
    ]
    arcs = _def_arcs(
        _BIZ_AXIS,
        "x:SegmentDomain",
        [
            ("x:SegmentDomain", "x:AllMember"),
            ("x:AllMember", "x:AlphaMember"),
            ("x:AllMember", "x:BetaMember"),
        ],
    )
    graph = _build_segments(
        facts, concept_qname=_REV, axis_qname=_BIZ_AXIS, definition_arcs=arcs
    )
    assert graph.classification is not None
    assert graph.classification.kind == "nested_members"
    assert graph.classification.subsumed == ("x:AlphaMember", "x:BetaMember")
    assert graph.classification.basis == "arcs"
    assert graph.filed_member_sum == 2000.0
    assert graph.verified is True


def _overlap_facts() -> list[XbrlFact]:
    """Total 1000 filed as a 450/550 pair and as ten 100 details."""
    facts = [
        _segment_fact(_REV, 1000.0),
        _segment_fact(_REV, 450.0, {_BIZ_AXIS: "x:ProductMember"}),
        _segment_fact(_REV, 550.0, {_BIZ_AXIS: "x:ServiceOtherMember"}),
    ]
    facts.extend(
        _segment_fact(_REV, 100.0, {_BIZ_AXIS: f"x:Detail{i}Member"}) for i in range(10)
    )
    return facts


def _declaring_entry(category: str, members: list[str]) -> CatalogEntry:
    """One role entry whose tree declares the axis subtree over members."""
    arcs = [
        PresentationArc("x:Root", _REV, role_uri="x:role"),
        PresentationArc(_REV, _BIZ_AXIS, role_uri="x:role"),
        PresentationArc(_BIZ_AXIS, "x:Domain", role_uri="x:role"),
    ]
    arcs.extend(
        PresentationArc("x:Domain", member, role_uri="x:role") for member in members
    )
    return CatalogEntry(
        role_uri="x:role",
        title="Role",
        category=category,
        family=None,
        concept_count=0,
        roots=("x:Root",),
        arcs=tuple(arcs),
    )


_PAIR = ["x:ProductMember", "x:ServiceOtherMember"]
_DETAILS = [f"x:Detail{i}Member" for i in range(10)]


def test_segment_breakdown_serves_statement_declared_partition() -> None:
    """A statement role's declared partition serves over the finest."""
    entries = (
        _declaring_entry(DISCLOSURE, _DETAILS),
        _declaring_entry(STATEMENT, _PAIR),
    )
    graph = _build_segments(
        _overlap_facts(),
        concept_qname=_REV,
        axis_qname=_BIZ_AXIS,
        catalog_entries=entries,
    )
    assert {m.member_qname for m in graph.members} == set(_PAIR)
    assert graph.verified is True
    assert graph.filed_member_sum == 2000.0
    assert len(graph.alternates) == 1
    assert {m.member_qname for m in graph.alternates[0]} == set(_DETAILS)
    assert sum(m.value for m in graph.alternates[0]) == 1000.0


def test_segment_breakdown_serves_declared_partition_from_any_role() -> None:
    """A partition declared only by a detail role still outranks finest."""
    graph = _build_segments(
        _overlap_facts(),
        concept_qname=_REV,
        axis_qname=_BIZ_AXIS,
        catalog_entries=(_declaring_entry(DISCLOSURE, _PAIR),),
    )
    assert {m.member_qname for m in graph.members} == set(_PAIR)
    assert graph.verified is True


def test_segment_breakdown_serves_finest_without_declaration() -> None:
    """No declared partition: the finest complete partition serves."""
    graph = _build_segments(_overlap_facts(), concept_qname=_REV, axis_qname=_BIZ_AXIS)
    assert {m.member_qname for m in graph.members} == set(_DETAILS)
    assert graph.verified is True
    assert len(graph.alternates) == 1
    assert {m.member_qname for m in graph.alternates[0]} == set(_PAIR)
