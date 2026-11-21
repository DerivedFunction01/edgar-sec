from __future__ import annotations

from tests.apps.client.statements.topics.topic_fixtures import (
    _BIZ_AXIS,
    _GEO_AXIS,
    _REV,
    _build_segments,
    _segment_fact,
)


def test_segment_breakdown_verifies_members_against_total() -> None:
    """Single-axis members summing to the total verify; other facts stay out."""
    facts = [
        _segment_fact(_REV, 1000.0),
        _segment_fact(_REV, 600.0, {_BIZ_AXIS: "x:AlphaMember"}),
        _segment_fact(_REV, 400.0, {_BIZ_AXIS: "x:BetaMember"}),
        _segment_fact(_REV, 999.0, {_BIZ_AXIS: "x:AlphaMember", _GEO_AXIS: "x:US"}),
        _segment_fact(_REV, 700.0, {_GEO_AXIS: "x:US"}),
        _segment_fact(_REV, 300.0, {_GEO_AXIS: "x:NonUS"}),
    ]
    graph = _build_segments(facts, concept_qname=_REV, axis_qname=_BIZ_AXIS)
    assert graph.total == 1000.0
    assert graph.member_sum == 1000.0
    assert graph.verified is True
    assert graph.discrepancy == 0.0
    assert {m.member_qname: m.value for m in graph.members} == {
        "x:AlphaMember": 600.0,
        "x:BetaMember": 400.0,
    }
    default = _build_segments(facts)
    assert default.concept_qname == _REV
    assert default.axis_qname == _BIZ_AXIS
    assert default.verified is True


def test_segment_member_labels_resolve_label_first_then_split() -> None:
    """Member labels come from the labels mapping, else the split name."""
    facts = [
        _segment_fact(_REV, 1000.0),
        _segment_fact(_REV, 600.0, {_BIZ_AXIS: "x:AlphaMember"}),
        _segment_fact(_REV, 400.0, {_BIZ_AXIS: "x:BetaMember"}),
    ]
    graph = _build_segments(
        facts,
        concept_qname=_REV,
        axis_qname=_BIZ_AXIS,
        labels={"x:AlphaMember": "Alpha Segment"},
    )
    labels_by_member = {m.member_qname: m.label for m in graph.members}
    assert labels_by_member == {
        "x:AlphaMember": "Alpha Segment",
        "x:BetaMember": "Beta",
    }


def test_segment_breakdown_reports_gap_without_forcing_balance() -> None:
    """Members short of the total serve with the discrepancy shown."""
    facts = [
        _segment_fact(_REV, 1000.0),
        _segment_fact(_REV, 600.0, {_BIZ_AXIS: "x:AlphaMember"}),
        _segment_fact(_REV, 300.0, {_BIZ_AXIS: "x:BetaMember"}),
    ]
    graph = _build_segments(facts, concept_qname=_REV, axis_qname=_BIZ_AXIS)
    assert graph.member_sum == 900.0
    assert graph.verified is False
    assert graph.discrepancy == 100.0


def test_segment_breakdown_counts_each_member_once() -> None:
    """A repeated member fact is one antichain element, not a double count."""
    facts = [
        _segment_fact(_REV, 1000.0),
        _segment_fact(_REV, 600.0, {_BIZ_AXIS: "x:AlphaMember"}, decimals=-6),
        _segment_fact(_REV, 600.0, {_BIZ_AXIS: "x:AlphaMember"}, decimals=-3),
        _segment_fact(_REV, 400.0, {_BIZ_AXIS: "x:BetaMember"}),
    ]
    graph = _build_segments(facts, concept_qname=_REV, axis_qname=_BIZ_AXIS)
    assert len(graph.members) == 2
    assert graph.verified is True
