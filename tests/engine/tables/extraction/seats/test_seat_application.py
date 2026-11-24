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
    seat_applier,
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


def test_seat_applier_binds_a_decision_under_its_public_name() -> None:
    def seat_one(
        geometry: GeometryText, result: CompetitionResult
    ) -> CompetitionResult:
        return result

    apply = seat_applier(seat_one, "apply_example_seat")
    assert apply.__name__ == "apply_example_seat"
    geometries = [GeometryText()]
    results = [_result()]
    assert apply(geometries, results) == results


def test_seat_role_names_a_fragment_a_continuation() -> None:
    assert seat_role(GeometryText(stubs=("Revenue",))) == "continuation"


def test_seat_role_names_a_captioned_geometry_a_head() -> None:
    assert seat_role(GeometryText(caption="Segment information")) == "head"


def test_seat_role_names_a_long_uncaptioned_geometry_standalone() -> None:
    stubs = tuple(f"Line {n}" for n in range(9))
    assert seat_role(GeometryText(stubs=stubs)) == "standalone"
