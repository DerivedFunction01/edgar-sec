"""Geometry-only positions and association for mark and label spans."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, TypeVar


class MarkLabelRelation(StrEnum):
    LEFT = "left"
    RIGHT = "right"
    ABOVE = "above"
    BELOW = "below"
    SAME_CELL = "same_cell"
    SAME_LINE = "same_line"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class SpanPosition:
    row: int
    column: int | None
    line: int
    offset: int
    end: int


Positioned = TypeVar("Positioned")


@dataclass(frozen=True, slots=True)
class MarkLabelAssociation(Generic[Positioned]):
    candidate: Positioned | None
    relation: MarkLabelRelation


def relation_between(mark: SpanPosition, label: SpanPosition) -> MarkLabelRelation:
    if mark.row != label.row:
        return (
            MarkLabelRelation.ABOVE if mark.row < label.row else MarkLabelRelation.BELOW
        )
    if mark.column is not None and label.column is not None:
        if mark.column != label.column:
            return (
                MarkLabelRelation.LEFT
                if mark.column < label.column
                else MarkLabelRelation.RIGHT
            )
        if mark.line != label.line:
            return (
                MarkLabelRelation.ABOVE
                if mark.line < label.line
                else MarkLabelRelation.BELOW
            )
    elif mark.line != label.line:
        return (
            MarkLabelRelation.ABOVE
            if mark.line < label.line
            else MarkLabelRelation.BELOW
        )
    if mark.end <= label.offset:
        return MarkLabelRelation.LEFT
    if label.end <= mark.offset:
        return MarkLabelRelation.RIGHT
    return MarkLabelRelation.SAME_LINE


def _distance(mark: SpanPosition, label: SpanPosition) -> tuple[int, int, int]:
    row_distance = abs(mark.row - label.row)
    column_distance = (
        abs(mark.column - label.column)
        if mark.column is not None and label.column is not None
        else 0
    )
    cell_distance = row_distance + column_distance
    if cell_distance:
        return (cell_distance, 0, 0)
    line_distance = abs(mark.line - label.line)
    if line_distance:
        return (0, line_distance, 0)
    span_distance = max(
        0,
        label.offset - mark.end,
        mark.offset - label.end,
    )
    return (0, 0, span_distance)


def select_unique_nearest(
    target: SpanPosition,
    candidates: Sequence[Positioned],
    *,
    position_of: Callable[[Positioned], SpanPosition],
) -> Positioned | None:
    if not candidates:
        return None
    ranked = sorted(
        (
            (_distance(position_of(candidate), target), candidate)
            for candidate in candidates
        ),
        key=lambda item: item[0],
    )
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        return None
    return ranked[0][1]


def associate_nearest(
    target: SpanPosition,
    candidates: Sequence[Positioned],
    *,
    position_of: Callable[[Positioned], SpanPosition],
) -> MarkLabelAssociation[Positioned]:
    candidate = select_unique_nearest(target, candidates, position_of=position_of)
    if candidate is None:
        return MarkLabelAssociation(None, MarkLabelRelation.UNRESOLVED)
    return MarkLabelAssociation(
        candidate,
        relation_between(position_of(candidate), target),
    )


__all__ = [
    "MarkLabelAssociation",
    "MarkLabelRelation",
    "SpanPosition",
    "associate_nearest",
    "relation_between",
    "select_unique_nearest",
]
