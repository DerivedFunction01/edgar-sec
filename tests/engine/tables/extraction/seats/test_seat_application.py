"""Seat application: the shared per-geometry pass and the
seated group's role from the geometry's shape.
"""

from __future__ import annotations

import pytest

from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
    CompetitionResult,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
)
from edgar_sec.engine.tables.extraction.seats.seat_application import (
    apply_seat,
    seat_role,
)


def _result() -> CompetitionResult:
    return CompetitionResult(claims=(), contested=(), scores={})


def test_apply_seat_pairs_each_geometry_with_its_result() -> None:
    seen: list[tuple[GeometryText, CompetitionResult]] = []

    def seat_one(
        geometry: GeometryText, result: CompetitionResult
    ) -> CompetitionResult:
        seen.append((geometry, result))
        return result

    geometries = [GeometryText(), GeometryText(caption="Notes")]
    results = [_result(), _result()]
    out = apply_seat(seat_one, geometries, results)
    assert out == results
    assert seen == list(zip(geometries, results, strict=True))


def test_apply_seat_refuses_a_length_mismatch() -> None:
    def seat_one(
        geometry: GeometryText, result: CompetitionResult
    ) -> CompetitionResult:
        return result

    with pytest.raises(ValueError):
        apply_seat(seat_one, [GeometryText()], [])


def test_seat_role_names_a_fragment_a_continuation() -> None:
    assert seat_role(GeometryText(is_fragment=True)) == "continuation"


def test_seat_role_names_a_captioned_geometry_a_head() -> None:
    assert seat_role(GeometryText(caption="Segment information")) == "head"


def test_seat_role_names_a_bare_geometry_standalone() -> None:
    assert seat_role(GeometryText()) == "standalone"
