"""Pins for the children-by-parent home (Wave 2B).
The grouping lives in ``presentation``; ``location`` binds it.
"""

from __future__ import annotations

from types import SimpleNamespace

from edgar_sec.apps.client import location, presentation


def _arc(parent: str, child: str, order: float | None) -> SimpleNamespace:
    return SimpleNamespace(parent_qname=parent, child_qname=child, order=order)


def test_binding_is_the_presentation_home() -> None:
    assert location._children_by_parent is presentation._children_by_parent


def test_grouping_and_sort_verdicts() -> None:
    arcs = (
        _arc("p", "b", None),
        _arc("p", "a", 2.0),
        _arc("q", "c", 1.0),
    )
    children = presentation._children_by_parent(arcs)
    assert [arc.child_qname for arc in children["p"]] == ["b", "a"]
    assert [arc.child_qname for arc in children["q"]] == ["c"]
    assert presentation._children_by_parent(()) == {}
