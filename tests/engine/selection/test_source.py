"""Unit tests for engine.selection.source: bounded candidate access.

Every test here concerns a bound, because that is the module's contract: a
selector must be able to ask a corpus of any size for a pool of any filter
without materializing it, and must never be able to inject SQL through a
policy document.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from edgar_sec.domain.filing_catalog.filters import parse_date_selection
from edgar_sec.engine.selection.source import (
    OCCURRENCE_COLUMNS,
    POOL_COLUMNS,
    CandidateFilters,
    CandidateSource,
    SelectionSessionError,
)
from tests.engine.selection.conftest import make_locator, write_snapshot


def _source(snapshot: Path, **kwargs: object) -> CandidateSource:
    return CandidateSource(snapshot, "test-seed", **kwargs)


def test_pool_rows_carry_exactly_the_declared_columns(
    snapshot_dir: Path,
) -> None:
    with _source(snapshot_dir).session() as source:
        rows = source.candidate_page(0)
    assert rows
    assert set(rows[0]) == set(POOL_COLUMNS)


def test_queries_outside_a_session_are_refused(snapshot_dir: Path) -> None:
    """Using a closed source must fail loudly rather than return nothing."""
    with pytest.raises(SelectionSessionError, match="session is not open"):
        _source(snapshot_dir).candidate_page(0)


def test_a_missing_snapshot_is_reported_up_front(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="feature snapshot is missing"):
        CandidateSource(tmp_path / "absent", "seed")


def test_rejects_a_non_positive_page_size(snapshot_dir: Path) -> None:
    with pytest.raises(ValueError, match="page_size must be at least 1"):
        _source(snapshot_dir, page_size=0)


def test_pool_for_value_matches_and_respects_the_limit(
    snapshot_dir: Path,
) -> None:
    with _source(snapshot_dir).session() as source:
        legacy = source.pool_for_value("era", "legacy")
        assert legacy
        assert all(row["era"] == "legacy" for row in legacy)
        assert len(source.pool_for_value("era", "legacy", limit=2)) == 2


def test_pool_for_value_rejects_an_unknown_dimension(snapshot_dir: Path) -> None:
    """v1 interpolated the dimension name straight into the predicate.

    A policy could therefore query any column the snapshot carried. Only the
    declared vocabulary is addressable.
    """
    with (
        _source(snapshot_dir).session() as source,
        pytest.raises(ValueError, match="unknown selection dimension"),
    ):
        source.pool_for_value("document_path", "x")
    with (
        _source(snapshot_dir).session() as source,
        pytest.raises(ValueError, match="unknown selection dimension"),
    ):
        source.pool_for_composite({"report_year": 2020})


def test_a_quote_shaped_dimension_value_is_bound_not_interpolated(
    snapshot_dir: Path,
) -> None:
    """The value comes from a policy document, so it must never reach SQL text."""
    hostile = "x'; DROP TABLE selected_keys; --"
    with _source(snapshot_dir).session() as source:
        rows = source.pool_for_value("era", hostile)
        # The exclusion table survives, which it would not if the value had been
        # spliced into the query.
        assert rows == []
        assert source.candidate_page(0)


def test_pool_for_composite_conjoins_every_filter(snapshot_dir: Path) -> None:
    with _source(snapshot_dir).session() as source:
        rows = source.pool_for_composite({"era": "legacy", "form_family": "10-K"})
    assert rows
    assert all(row["era"] == "legacy" for row in rows)


def test_pool_for_ciks_caps_each_cik_separately(tmp_path: Path) -> None:
    """A seed registrant must not be able to consume the whole budget."""
    locators = [
        make_locator(index, company_family=f"f{index}", cik=f"0000000000{cik}")
        for index, cik in enumerate(["1"] * 4 + ["2"] * 4 + ["3"] * 4)
    ]
    snapshot = write_snapshot(tmp_path / "ciks", locators)
    ciks = ["00000000001", "00000000002", "00000000003"]
    with _source(snapshot).session() as source:
        rows = source.pool_for_ciks(ciks, limit_per_cik=2)
    counts: dict[str, int] = {}
    for row in rows:
        cik = row["representative_cik"]
        counts[cik] = counts.get(cik, 0) + 1
    assert set(counts) == set(ciks)
    assert max(counts.values()) == 2


def test_pool_for_ciks_with_no_ciks_returns_nothing(snapshot_dir: Path) -> None:
    with _source(snapshot_dir).session() as source:
        assert source.pool_for_ciks([]) == []


def test_paging_is_stable_and_does_not_overlap(snapshot_dir: Path) -> None:
    with _source(snapshot_dir, page_size=8).session() as source:
        first = [row["document_locator_key"] for row in source.candidate_page(0)]
        second = [row["document_locator_key"] for row in source.candidate_page(1)]
    assert len(first) == 8
    assert set(first).isdisjoint(second)


def test_paging_stops_past_the_end_of_the_pool(snapshot_dir: Path) -> None:
    with _source(snapshot_dir, page_size=8).session() as source:
        assert source.candidate_page(99) == []


def test_selected_keys_are_excluded_from_later_pools(
    snapshot_dir: Path,
) -> None:
    """A selected locator must not be re-offered, or the fill could loop on it."""
    with _source(snapshot_dir).session() as source:
        first = source.candidate_page(0)
        claimed = first[0]["document_locator_key"]
        source.register_selected([claimed])
        assert claimed not in {
            row["document_locator_key"] for row in source.candidate_page(0)
        }
        assert claimed not in {
            row["document_locator_key"]
            for row in source.pool_for_value("era", "legacy")
        }


def test_register_selected_replaces_rather_than_accumulates(
    snapshot_dir: Path,
) -> None:
    with _source(snapshot_dir).session() as source:
        page = source.candidate_page(0)
        source.register_selected([row["document_locator_key"] for row in page[:3]])
        source.register_selected([page[0]["document_locator_key"]])
        remaining = {row["document_locator_key"] for row in source.candidate_page(0)}
    assert page[0]["document_locator_key"] not in remaining


def test_add_selected_appends_one_key(snapshot_dir: Path) -> None:
    with _source(snapshot_dir).session() as source:
        page = source.candidate_page(0)
        for row in page[:2]:
            source.add_selected(row["document_locator_key"])
        remaining = {row["document_locator_key"] for row in source.candidate_page(0)}
    assert {row["document_locator_key"] for row in page[:2]}.isdisjoint(remaining)


def test_load_candidates_preserves_the_requested_order(
    snapshot_dir: Path,
) -> None:
    """A parent selection's rows must line up with its key order."""
    with _source(snapshot_dir).session() as session:
        reversed_keys = ["loc-0005", "loc-0000", "loc-0003"]
        rows = session.load_candidates_for_locators(reversed_keys)
    assert [row["document_locator_key"] for row in rows] == reversed_keys


def test_load_candidates_rejects_a_key_the_snapshot_lacks(
    snapshot_dir: Path,
) -> None:
    with (
        _source(snapshot_dir).session() as source,
        pytest.raises(ValueError, match="absent from the selection snapshot"),
    ):
        source.load_candidates_for_locators(["loc-0000", "loc-nope"])


def test_load_occurrences_returns_every_co_filer(snapshot_dir: Path) -> None:
    """One document, two registrants, two occurrences: both are work items."""
    locators = [make_locator(index, company_family=f"f{index}") for index in range(2)]
    occurrences = [
        {
            "occurrence_id": "occ-a",
            "document_locator_key": "loc-0000",
            "source_cik": "0000000000",
        },
        {
            "occurrence_id": "occ-b",
            "document_locator_key": "loc-0000",
            "source_cik": "0000000009",
        },
        {"occurrence_id": "occ-c", "document_locator_key": "loc-0001"},
    ]
    snapshot = write_snapshot(snapshot_dir.parent / "cofiled", locators, occurrences)
    with _source(snapshot).session() as source:
        rows = source.load_occurrences_for_locators(["loc-0000"])
    assert [row["occurrence_id"] for row in rows] == ["occ-a", "occ-b"]
    assert set(rows[0]) == set(OCCURRENCE_COLUMNS)


def test_occurrences_come_back_in_locator_then_occurrence_order(
    snapshot_dir: Path,
) -> None:
    with _source(snapshot_dir).session() as source:
        rows = source.load_occurrences_for_locators(
            ["loc-0003", "loc-0001", "loc-0002"]
        )
    keys = [row["document_locator_key"] for row in rows]
    assert keys == sorted(keys)


def test_empty_requests_return_empty_without_touching_storage(
    snapshot_dir: Path,
) -> None:
    with _source(snapshot_dir).session() as source:
        assert source.load_candidates_for_locators([]) == []
        assert source.load_occurrences_for_locators([]) == []


# ------------------------------------------------------------------ filters


def test_max_reported_size_filter_narrows_the_pool(tmp_path: Path) -> None:
    locators = [make_locator(index, company_family=f"f{index}") for index in range(4)]
    for row in locators:
        row["reported_size"] = 500
    locators[0]["reported_size"] = 10_000_000
    snapshot = write_snapshot(tmp_path / "size", locators)
    with _source(
        snapshot, filters=CandidateFilters(max_reported_size=1_000)
    ).session() as source:
        rows = source.candidate_page(0)
    assert "loc-0000" not in {row["document_locator_key"] for row in rows}


def test_document_suffix_filter_narrows_the_pool(tmp_path: Path) -> None:
    locators = [make_locator(index, company_family=f"f{index}") for index in range(4)]
    locators[0]["document_path"] = "filing.htm"
    locators[1]["document_path"] = "filing.txt"
    snapshot = write_snapshot(tmp_path / "suffix", locators)
    with _source(
        snapshot, filters=CandidateFilters(document_suffixes=("txt",))
    ).session() as source:
        rows = source.candidate_page(0)
    assert [row["document_locator_key"] for row in rows] == ["loc-0001"]


def test_an_unconstrained_filter_predicate_is_true() -> None:
    assert CandidateFilters().predicate() == "TRUE"


# --- the date selection -----------------------------------------------------


def _dated_locators() -> list[dict[str, Any]]:
    """Locators across four quarters, two forms, and one unreadable date."""
    rows: list[dict[str, Any]] = []
    index = 0
    for form, dates in (
        ("10-K", ["2023-03-31", "2023-06-30", "2023-09-30", "2023-12-31"]),
        ("8-K", ["2024-03-31", "2024-06-30"]),
    ):
        for report_date in dates:
            index += 1
            rows.append(
                make_locator(
                    index,
                    company_family=f"f{index}",
                    form=form,
                    report_date=report_date,
                    report_year=int(report_date[:4]),
                )
            )
    index += 1
    rows.append(
        make_locator(index, company_family="nodate", report_date="", report_year=None)
    )
    return rows


def test_no_date_selection_keeps_every_locator(tmp_path: Path) -> None:
    snapshot = write_snapshot(tmp_path / "all", _dated_locators())
    with _source(snapshot).session() as source:
        rows = source.candidate_page(0)
    assert len(rows) == 7


def test_a_date_selection_excludes_a_locator_with_no_readable_date(
    tmp_path: Path,
) -> None:
    """The same asymmetry the catalog contract states: nonempty excludes them."""
    snapshot = write_snapshot(tmp_path / "dated", _dated_locators())
    with _source(
        snapshot,
        filters=CandidateFilters(date_selection=parse_date_selection("2000..2030")),
    ).session() as source:
        rows = source.candidate_page(0)
    assert len(rows) == 6
    assert all(row["document_locator_key"] != "loc-0007" for row in rows)


def test_recurring_periods_narrow_the_pool(tmp_path: Path) -> None:
    snapshot = write_snapshot(tmp_path / "q1", _dated_locators())
    with _source(
        snapshot,
        filters=CandidateFilters(date_selection=parse_date_selection("@Q1")),
    ).session() as source:
        rows = source.candidate_page(0)
    assert sorted(row["document_locator_key"] for row in rows) == [
        "loc-0001",
        "loc-0005",
    ]


def test_the_date_filter_reaches_every_pool_kind(tmp_path: Path) -> None:
    """Not just paging: a floor must not be able to draw an out-of-range row."""
    snapshot = write_snapshot(tmp_path / "kinds", _dated_locators())
    filters = CandidateFilters(
        date_selection=parse_date_selection("2023-12"), document_suffixes=()
    )
    with _source(snapshot, filters=filters).session() as source:
        by_value = source.pool_for_value("form", "8-K", limit=10)
        by_composite = source.pool_for_composite({"form": "8-K"}, limit=10)
        by_cik = source.pool_for_ciks(["0000000005"], limit_per_cik=5)
        page = source.candidate_page(0)
        availability = source.cell_availability()
    assert by_value == []
    assert by_composite == []
    assert by_cik == []
    # Only the one December 2023 row survives, and every pool kind agrees.
    assert [row["document_locator_key"] for row in page] == ["loc-0004"]
    assert availability == [("10-K", "modern", 1)]


def test_cell_availability_counts_only_the_rows_a_pool_could_draw(
    tmp_path: Path,
) -> None:
    locators = [
        make_locator(1, company_family="a", form="10-K", era="modern"),
        make_locator(2, company_family="b", form="10-K", era="modern"),
        make_locator(3, company_family="c", form="8-K", era="legacy"),
    ]
    snapshot = write_snapshot(tmp_path / "cells", locators)
    with _source(snapshot).session() as source:
        assert source.cell_availability() == [
            ("10-K", "modern", 2),
            ("8-K", "legacy", 1),
        ]
        source.register_selected(["loc-0001"])
        assert source.cell_availability() == [
            ("10-K", "modern", 1),
            ("8-K", "legacy", 1),
        ]


def test_a_pool_for_one_cell_returns_only_that_cell(tmp_path: Path) -> None:
    locators = [
        make_locator(1, company_family="a", form="10-K", era="modern"),
        make_locator(2, company_family="b", form="10-K", era="legacy"),
    ]
    snapshot = write_snapshot(tmp_path / "one-cell", locators)
    with _source(snapshot).session() as source:
        rows = source.pool_for_cell("10-K", "legacy", limit=10)
    assert [row["document_locator_key"] for row in rows] == ["loc-0002"]
