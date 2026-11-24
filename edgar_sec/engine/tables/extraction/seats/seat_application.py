"""Seat application: the per-geometry pass and group role
every final-pass family seat shares.
"""

from __future__ import annotations

from collections.abc import Callable

from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
    CompetitionResult,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
)

SeatOne = Callable[[GeometryText, CompetitionResult], CompetitionResult]


def seat_role(geometry: GeometryText) -> str:
    """The seated group's role from the geometry's shape."""
    return (
        "continuation"
        if geometry.is_fragment
        else "head"
        if geometry.caption.strip()
        else "standalone"
    )


def apply_seat(
    seat_one: SeatOne,
    geometries: list[GeometryText] | tuple[GeometryText, ...],
    results: list[CompetitionResult],
) -> list[CompetitionResult]:
    """Apply one seat's per-geometry decision across a filing."""
    return [
        seat_one(geometry, result)
        for geometry, result in zip(geometries, results, strict=True)
    ]


SeatApplier = Callable[
    [list[GeometryText] | tuple[GeometryText, ...], list[CompetitionResult]],
    list[CompetitionResult],
]


def seat_applier(seat_one: SeatOne, name: str) -> SeatApplier:
    """Bind one seat's per-geometry decision as its apply pass."""

    def apply(
        geometries: list[GeometryText] | tuple[GeometryText, ...],
        results: list[CompetitionResult],
    ) -> list[CompetitionResult]:
        return apply_seat(seat_one, geometries, results)

    apply.__name__ = name
    apply.__qualname__ = name
    return apply
