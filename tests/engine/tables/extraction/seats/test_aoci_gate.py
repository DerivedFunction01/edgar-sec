"""AOCI gate: specimen tests for the priced claim-shape dialects,
the Cure 1 core-shape relaxation, and the subject guard."""

from __future__ import annotations

from types import SimpleNamespace

from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
)
from edgar_sec.engine.tables.extraction.seats.aoci_gate import (
    aoci_gate_detail,
    claim_shape,
)

_MOVEMENT_STUBS = (
    "Other comprehensive income before reclassifications",
    "Amounts reclassified from accumulated other comprehensive income",
)


def _score(**by_channel: float):
    return {"aoci_rollforward": SimpleNamespace(by_channel=by_channel)}


def test_walk_accepts_dated_aoci_balance_stubs() -> None:
    geometry = GeometryText(
        stubs=(
            "AOCI Balance, December 31, 2023",
            *_MOVEMENT_STUBS,
            "AOCI Balance, December 31, 2024",
        ),
    )
    walk, subject = claim_shape(geometry)
    assert walk
    assert subject


def test_walk_accepts_beginning_of_period_pair() -> None:
    geometry = GeometryText(
        stubs=(
            "Balance at beginning of period",
            *_MOVEMENT_STUBS,
            "Accumulated other comprehensive income",
        ),
    )
    walk, subject = claim_shape(geometry)
    assert walk
    assert subject


def test_walk_accepts_header_carried_beginning_balance() -> None:
    geometry = GeometryText(
        stubs=(*_MOVEMENT_STUBS, "Balance at March 31, 2023"),
        headers=("Balance at December 31, 2022", "Foreign Currency", "Total"),
    )
    walk, subject = claim_shape(geometry)
    assert walk
    assert subject


def test_walk_rejects_movements_without_a_balance_pair() -> None:
    geometry = GeometryText(stubs=_MOVEMENT_STUBS)
    walk, subject = claim_shape(geometry)
    assert not walk
    assert subject


def test_cure1_relaxes_when_the_core_shape_is_present() -> None:
    geometry = GeometryText(
        stubs=(
            "Balance at beginning of period",
            *_MOVEMENT_STUBS,
            "Accumulated other comprehensive income",
        ),
    )
    detail = aoci_gate_detail(
        ["aoci_rollforward", "equity_statement"], _score(), geometry
    )
    assert detail is None


def test_cure1_bars_an_equity_seated_claim_without_the_core_shape() -> None:
    geometry = GeometryText(stubs=_MOVEMENT_STUBS)
    detail = aoci_gate_detail(
        ["aoci_rollforward", "equity_statement"], _score(), geometry
    )
    assert detail == "aoci: no rollforward evidence"


def test_subject_guard_bars_a_claim_with_no_aoci_subject() -> None:
    geometry = GeometryText(
        stubs=("Balance, January 1, 2024", "Balance, March 31, 2024"),
        headers=("Balance, January 1, 2024",),
    )
    detail = aoci_gate_detail(
        ["aoci_rollforward", "equity_statement"], _score(stub=9.0), geometry
    )
    assert detail == "aoci: claim shape missing subject"


def test_subject_guard_spares_a_claim_with_a_subject() -> None:
    geometry = GeometryText(
        stubs=(
            "Balance, January 1, 2024",
            *_MOVEMENT_STUBS,
            "Balance, March 31, 2024",
        ),
    )
    detail = aoci_gate_detail(
        ["aoci_rollforward", "equity_statement"], _score(stub=9.0), geometry
    )
    assert detail is None
