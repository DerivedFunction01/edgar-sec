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
    component_grid,
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


def test_walk_accepts_ending_balance_stub_with_beginning_header() -> None:
    geometry = GeometryText(
        stubs=(*_MOVEMENT_STUBS, "Ending Balance at August 2, 2025"),
        headers=("Beginning Balance at May 3, 2025", "$ 191"),
    )
    walk, subject = claim_shape(geometry)
    assert walk
    assert subject


def test_walk_accepts_bare_date_pair_with_movements() -> None:
    geometry = GeometryText(
        stubs=(*_MOVEMENT_STUBS, "September 30, 2024"),
        headers=("Available-for-Sale Securities", "Total", "September 30, 2023"),
    )
    walk, subject = claim_shape(geometry)
    assert walk
    assert subject


def test_component_grid_accepts_a_component_walk() -> None:
    geometry = GeometryText(
        stubs=(
            "Balance, December 31, 2024",
            *_MOVEMENT_STUBS,
            "Balance, September 30, 2025",
        ),
        headers=("Gain on Swaps", "Accumulated Other Comprehensive Income"),
    )
    assert component_grid(geometry)


def test_component_grid_accepts_one_movement_with_framing() -> None:
    geometry = GeometryText(
        stubs=(
            "Balance, December 31, 2008",
            "Net realized (gains) losses reclassified into earnings",
            "Balance, December 31, 2009",
        ),
        headers=("Available-for-Sale Debt Securities", "Derivatives", "Total"),
        lead="The following table presents the changes in accumulated "
        "other comprehensive income",
    )
    assert component_grid(geometry)


def test_component_grid_bars_an_equity_statement_by_its_headers() -> None:
    geometry = GeometryText(
        stubs=(
            "Balance at January 1, 2022",
            "Other comprehensive income",
            "Balance at September 30, 2022",
        ),
        headers=(
            "Accumulated Capital",
            "Accumulated Deficit",
            "Accumulated Other Comprehensive Income/(Loss)",
            "Noncontrolling Interests",
            "Total",
        ),
    )
    assert not component_grid(geometry)


def test_component_grid_bars_an_equity_statement_by_its_stub_sections() -> None:
    geometry = GeometryText(
        stubs=(
            "Common Stock",
            "Balance at beginning of period",
            "Balance at end of period",
            "Additional Paid-In Capital",
            *_MOVEMENT_STUBS,
        ),
    )
    assert not component_grid(geometry)


def test_component_grid_bars_a_cash_flow_section() -> None:
    geometry = GeometryText(
        stubs=(
            "Operating activities:",
            "Net income",
            "Unrealized loss on derivatives",
            "Unrealized foreign exchange (gain) loss",
            "Balance at beginning of period",
            "Balance at end of period",
        ),
    )
    assert not component_grid(geometry)


def test_component_grid_bars_a_fair_value_walk() -> None:
    geometry = GeometryText(
        stubs=(
            "Beginning balance",
            "Included in accumulated other comprehensive income (loss)",
            "Purchases",
            "Sales",
            "Ending balance",
        ),
    )
    assert not component_grid(geometry)


def test_component_grid_bars_a_single_movement_foreign_walk() -> None:
    geometry = GeometryText(
        stubs=(
            "Balance at beginning of period",
            "Additions",
            "Amortization",
            "Foreign currency translation and other",
            "Balance at end of period",
        ),
        headers=("Three Months Ended March 31,", "2023", "2022"),
    )
    assert not component_grid(geometry)
