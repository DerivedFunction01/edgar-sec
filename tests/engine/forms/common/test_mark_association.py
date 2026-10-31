"""Tests for geometry-only mark and label association."""

from edgar_sec.engine.forms.common.mark_association import (
    MarkLabelRelation,
    SpanPosition,
    associate_nearest,
    relation_between,
    select_unique_nearest,
)


def _position(
    row: int,
    column: int | None,
    line: int,
    offset: int,
    end: int,
) -> SpanPosition:
    return SpanPosition(row, column, line, offset, end)


def test_relations_cover_each_orientation() -> None:
    label = _position(2, 3, 0, 10, 20)
    positions = (
        (_position(2, 2, 0, 0, 2), MarkLabelRelation.LEFT),
        (_position(2, 4, 0, 0, 2), MarkLabelRelation.RIGHT),
        (_position(1, 3, 0, 0, 2), MarkLabelRelation.ABOVE),
        (_position(3, 3, 0, 0, 2), MarkLabelRelation.BELOW),
        (_position(2, 3, 1, 0, 2), MarkLabelRelation.BELOW),
        (_position(2, 3, 0, 15, 16), MarkLabelRelation.SAME_LINE),
    )

    assert [relation_between(mark, label) for mark, _ in positions] == [
        expected for _, expected in positions
    ]


def test_same_line_spans_keep_left_and_right_direction() -> None:
    label = _position(0, None, 0, 10, 20)

    assert relation_between(_position(0, None, 0, 0, 5), label) is (
        MarkLabelRelation.LEFT
    )
    assert relation_between(_position(0, None, 0, 25, 30), label) is (
        MarkLabelRelation.RIGHT
    )


def test_unique_nearest_selection_refuses_equal_distance_candidates() -> None:
    target = _position(1, 1, 0, 0, 1)
    candidates = (
        _position(0, 0, 0, 0, 1),
        _position(0, 2, 0, 0, 1),
    )

    assert (
        select_unique_nearest(
            target, candidates, position_of=lambda candidate: candidate
        )
        is None
    )
    association = associate_nearest(
        target, candidates, position_of=lambda candidate: candidate
    )
    assert association.candidate is None
    assert association.relation is MarkLabelRelation.UNRESOLVED


def test_unique_nearest_selection_uses_span_distance_within_a_cell() -> None:
    target = _position(0, 0, 0, 10, 15)
    candidates = (
        _position(0, 0, 0, 0, 5),
        _position(0, 0, 0, 19, 25),
    )

    assert (
        select_unique_nearest(
            target, candidates, position_of=lambda candidate: candidate
        )
        == candidates[1]
    )
