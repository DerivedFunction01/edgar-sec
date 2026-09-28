"""Unit tests for engine.selection.inventory: floor feasibility statistics.

The point of this module is to answer "can this corpus satisfy this policy"
*before* a selection runs, so the tests are about the report a policy author
acts on rather than about the SQL.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.engine.selection.inventory import (
    LOCATOR_ONLY_DIMENSIONS,
    OCCURRENCE_ONLY_DIMENSIONS,
    InventoryStatistics,
    UnknownDimensionError,
)
from tests.engine.selection.conftest import make_locator, write_snapshot


@pytest.fixture
def inventory(tmp_path: Path) -> InventoryStatistics:
    locators = [
        make_locator(
            index,
            company_family=f"family{index % 4}",
            company_name=f"Company {index % 4} Inc",
            sic_code="3571" if index < 6 else "7372",
            era=("legacy" if index % 2 == 0 else "modern"),
        )
        for index in range(20)
    ]
    return InventoryStatistics(write_snapshot(tmp_path / "inv", locators))


def test_value_counts_agree_on_the_dimension_grain(
    inventory: InventoryStatistics,
) -> None:
    """Locator-grain and occurrence-grain dimensions count different things.

    A locator dimension counts documents; an occurrence dimension counts
    distinct documents too, but only among the rows that carry the value. Mixing
    the two up would report zero rather than fail.
    """
    era = inventory.value_counts("era")
    assert {row["value"] for row in era} == {"legacy", "modern"}
    assert all(row["locator_count"] == 10 for row in era)

    sic = inventory.value_counts("sic_code")
    counts = {row["value"]: row["locator_count"] for row in sic}
    assert counts == {"3571": 6, "7372": 14}


def test_value_counts_are_ordered_by_supply(inventory: InventoryStatistics) -> None:
    rows = inventory.value_counts("sic_code")
    assert [row["locator_count"] for row in rows] == sorted(
        (row["locator_count"] for row in rows), reverse=True
    )


def test_value_counts_report_distinct_ciks(inventory: InventoryStatistics) -> None:
    for row in inventory.value_counts("era"):
        assert row["cik_count"] == 10


def test_value_counts_reject_an_unknown_dimension(
    inventory: InventoryStatistics,
) -> None:
    with pytest.raises(UnknownDimensionError, match="unknown selection dimension"):
        inventory.value_counts("report_path")


def test_dimension_grain_sets_cover_the_vocabulary() -> None:
    """A dimension in neither set would silently count on the wrong table."""

    assert not (LOCATOR_ONLY_DIMENSIONS & OCCURRENCE_ONLY_DIMENSIONS)
    assert "sic_code" in OCCURRENCE_ONLY_DIMENSIONS
    assert "era" in LOCATOR_ONLY_DIMENSIONS


def test_floor_feasibility_reports_a_satisfiable_floor(
    inventory: InventoryStatistics,
) -> None:
    report = inventory.check_floor_feasibility({"era": {"legacy": 4}})
    assert report["era"]["legacy"] == {
        "required": 4,
        "available": 10,
        "feasible": True,
        "deficit": 0,
    }


def test_floor_feasibility_quantifies_an_impossible_floor(
    inventory: InventoryStatistics,
) -> None:
    """A policy author needs to know by how much, not just that it fails."""
    report = inventory.check_floor_feasibility({"era": {"ancient": 4}})
    assert report["era"]["ancient"] == {
        "required": 4,
        "available": 0,
        "feasible": False,
        "deficit": 4,
    }


def test_floor_feasibility_covers_every_declared_dimension(
    inventory: InventoryStatistics,
) -> None:
    report = inventory.check_floor_feasibility(
        {"era": {"legacy": 1}, "sic_code": {"3571": 1}}
    )
    assert set(report) == {"era", "sic_code"}


def test_composite_feasibility_counts_matching_locators(
    inventory: InventoryStatistics,
) -> None:
    report = inventory.check_composite_feasibility(
        [{"filters": {"era": "legacy", "sic_code": "3571"}, "min": 3}]
    )
    assert len(report) == 1
    assert report[0]["required"] == 3
    assert report[0]["feasible"] is True
    # Six locators carry sic 3571, half of them legacy.
    assert report[0]["available"] == 3


def test_composite_feasibility_reports_an_unreachable_stratum(
    inventory: InventoryStatistics,
) -> None:
    report = inventory.check_composite_feasibility(
        [{"filters": {"era": "ancient"}, "min": 1}]
    )
    assert report[0]["available"] == 0
    assert report[0]["feasible"] is False


def test_composite_feasibility_rejects_an_unknown_dimension(
    inventory: InventoryStatistics,
) -> None:
    with pytest.raises(UnknownDimensionError, match="unknown selection dimension"):
        inventory.check_composite_feasibility(
            [{"filters": {"erra": "modern"}, "min": 1}]
        )


def test_composite_feasibility_with_no_composites_is_empty(
    inventory: InventoryStatistics,
) -> None:
    assert inventory.check_composite_feasibility([]) == []


def test_composite_feasibility_binds_a_quote_shaped_value(
    inventory: InventoryStatistics,
) -> None:
    """The value comes from a policy document and must never reach SQL text."""
    report = inventory.check_composite_feasibility(
        [{"filters": {"era": "x'; DROP TABLE t; --"}, "min": 1}]
    )
    assert report[0]["available"] == 0
