"""Unit tests for engine.selection.selector: the five-phase deficit fill.

The important test is
:func:`test_a_dominant_family_cannot_fill_the_selection`. A corpus where one
corporate group holds two thirds of the documents is the realistic shape of the
problem the six-part classification cap exists to solve: without it, a plain
sample of filings is mostly that group's subsidiaries.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from edgar_sec.engine.selection.policy import (
    EraBand,
    SeedFiler,
    SelectionPolicy,
)
from edgar_sec.engine.selection.selector import (
    CLASSIFICATION_DIMENSIONS,
    DeficitSelector,
    classification_signature,
)
from tests.engine.selection.conftest import (
    make_dominant_snapshot,
    make_locator,
    write_snapshot,
)


def test_selection_fills_the_target_and_reports_itself(
    snapshot_dir: Path, selection_policy: SelectionPolicy
) -> None:
    result = DeficitSelector(snapshot_dir, selection_policy).select()

    assert len(result.active_locators) == selection_policy.requested_units()
    assert len(result.active_candidates) == len(result.active_locators)
    assert len(result.active_occurrences) == len(result.active_locators)
    assert result.report["active_locators_count"] == len(result.active_locators)
    assert "coverage_distributions" in result.report


def test_selection_is_deterministic_for_one_seed(
    snapshot_dir: Path, selection_policy: SelectionPolicy
) -> None:
    """Same snapshot, same policy, same seed, same answer.

    Selection feeds acquisition, so a rerun that picked different documents
    would make the published plan a claim rather than a record.
    """
    first = DeficitSelector(snapshot_dir, selection_policy).select()
    second = DeficitSelector(snapshot_dir, selection_policy).select()
    assert first.active_locators == second.active_locators
    assert first.report == second.report


def test_a_different_seed_selects_differently(
    snapshot_dir: Path, selection_policy: SelectionPolicy
) -> None:
    """The seed is the tie-break, so it must actually reach the ordering."""
    other = SelectionPolicy(
        corpus_id=selection_policy.corpus_id,
        forms=selection_policy.forms,
        base_content_units=selection_policy.requested_units(),
        reserve_size=selection_policy.reserve_size,
        seed_cik_path="__absent__",
        seed="a-completely-different-seed",
    )
    baseline = DeficitSelector(snapshot_dir, selection_policy).select()
    seeded = DeficitSelector(snapshot_dir, other).select()
    assert baseline.active_locators != seeded.active_locators


def test_a_dominant_family_cannot_fill_the_selection(
    dominant_family_snapshot: Path,
) -> None:
    """One group holds 12 of 18 locators. The cap must stop it winning.

    Every locator here shares one classification signature except for the family
    name, so an uncapped fill would take all twelve. This is the invariant that
    keeps a quota-balanced sample from being a sample of one conglomerate.
    """
    policy = SelectionPolicy(
        corpus_id="dominant",
        forms=["10-K"],
        base_content_units=8,
        reserve_size=0,
        seed_cik_path="__absent__",
    )
    result = DeficitSelector(dominant_family_snapshot, policy).select()

    families = [candidate["company_family"] for candidate in result.active_candidates]
    assert len(result.active_locators) == 8
    assert families.count("megacorp") == 1, "family cap did not hold"
    assert len(set(families)) == 8, (
        "selection collapsed onto fewer entities than available"
    )


def test_the_cap_is_what_bounds_dominance(tmp_path: Path) -> None:
    """Lifting the cap must visibly admit more of the dominant family.

    Paired with
    :func:`test_a_dominant_family_cannot_fill_the_selection`, this shows the cap
    is the binding constraint rather than a side effect of pool ordering.
    """
    snapshot = make_dominant_snapshot(tmp_path / "lifted", others=3)

    def select(cap: int) -> list[str]:
        policy = SelectionPolicy(
            corpus_id="lifted",
            forms=["10-K"],
            base_content_units=10,
            reserve_size=0,
            seed_cik_path="__absent__",
            max_per_company_classification=cap,
        )
        result = DeficitSelector(snapshot, policy).select()
        return [candidate["company_family"] for candidate in result.active_candidates]

    # Twelve megacorp locators in one signature, plus three others: the cap of
    # one admits at most four candidates in total.
    capped = select(1)
    assert len(capped) == 4
    assert capped.count("megacorp") == 1

    uncapped = select(12)
    assert len(uncapped) == 10
    assert uncapped.count("megacorp") > 1


def test_an_unreachable_target_is_reported_as_a_shortfall(
    tmp_path: Path,
) -> None:
    """A selection the corpus cannot satisfy must say so, not claim success.

    The cap makes this reachable-set smaller than the requested budget. The
    report has to expose the difference, or a published plan would assert a
    quota it never met.
    """
    snapshot = make_dominant_snapshot(tmp_path / "short", others=3)
    policy = SelectionPolicy(
        corpus_id="short",
        forms=["10-K"],
        base_content_units=10,
        reserve_size=0,
        seed_cik_path="__absent__",
    )
    result = DeficitSelector(snapshot, policy).select()
    assert result.report["target_units"] == 10
    assert result.report["active_locators_count"] == 4
    assert result.report["deduplicated_company_classifications"] > 0


def test_capped_candidates_are_counted_in_the_report(
    dominant_family_snapshot: Path,
) -> None:
    policy = SelectionPolicy(
        corpus_id="dominant",
        forms=["10-K"],
        base_content_units=8,
        reserve_size=0,
        seed_cik_path="__absent__",
    )
    result = DeficitSelector(dominant_family_snapshot, policy).select()
    assert result.report["deduplicated_company_classifications"] > 0
    assert result.report["unique_company_families"] == 8


def test_classification_signature_has_six_dimensions() -> None:
    assert len(CLASSIFICATION_DIMENSIONS) == 6
    assert CLASSIFICATION_DIMENSIONS[0] == "company_family"


def test_classification_signature_falls_back_to_company_name() -> None:
    """An unclustered candidate still participates rather than escaping the cap."""
    candidate = {
        "company_name": "Example Co",
        "company_family": None,
        "form": "10-K",
        "era": "modern",
        "sic_code": "3571",
        "entity_type": "operating",
        "lifecycle_class": "active",
    }
    assert classification_signature(candidate)[0] == "example co"


def test_floors_are_satisfied_before_the_weighted_fill(
    snapshot_dir: Path, selection_policy: SelectionPolicy
) -> None:
    policy = SelectionPolicy(
        corpus_id="floors",
        forms=["10-K"],
        era_bands=[
            EraBand(name="legacy", end_year=2010),
            EraBand(name="modern", start_year=2010),
        ],
        base_content_units=8,
        reserve_size=0,
        seed_cik_path="__absent__",
        floors={"era": {"legacy": 4}},
    )
    result = DeficitSelector(snapshot_dir, policy).select()
    coverage = result.report["coverage_distributions"]["era"]
    assert coverage.get("legacy", 0) >= 4
    assert result.report["underfilled_floors"] == {}


def test_an_impossible_floor_is_reported_not_silently_ignored(
    snapshot_dir: Path,
) -> None:
    """A floor nothing can satisfy must show up in the report.

    Otherwise the plan publishes with a quota it never met and the reader has
    no way to know which one.
    """
    policy = SelectionPolicy(
        corpus_id="impossible",
        forms=["10-K"],
        era_bands=[EraBand(name="modern", start_year=2010)],
        base_content_units=4,
        reserve_size=0,
        seed_cik_path="__absent__",
        floors={"era": {"ancient": 3}},
    )
    result = DeficitSelector(snapshot_dir, policy).select()
    underfilled = result.report["underfilled_floors"]["era"]["ancient"]
    assert underfilled == {"required": 3, "selected": 0, "deficit": 3}
    assert len(result.active_locators) == 4


def test_composites_are_satisfied_before_single_dimension_floors(
    tmp_path: Path,
) -> None:
    """A conjunction is harder to satisfy than any one of its terms."""
    locators = [
        make_locator(index, company_family=f"fam{index % 5}") for index in range(20)
    ]
    locators[0].update({"form": "20-F", "era": "rare"})
    locators[1].update({"form": "20-F", "era": "rare"})
    snapshot = write_snapshot(tmp_path / "composites", locators)

    policy = SelectionPolicy(
        corpus_id="composites",
        forms=["10-K", "20-F"],
        base_content_units=4,
        reserve_size=0,
        seed_cik_path="__absent__",
        floors={"era": {"common": 2}},
        composites=[{"filters": {"form": "20-F", "era": "rare"}, "min": 2}],
    )
    result = DeficitSelector(snapshot, policy).select()
    chosen = {candidate["form"] for candidate in result.active_candidates}
    assert "20-F" in chosen, "the composite stratum was not satisfied"


def test_caps_bound_a_dimensions_share_of_the_target(tmp_path: Path) -> None:
    locators = [
        make_locator(index, company_family=f"fam{index}", company_name=f"Co {index}")
        for index in range(20)
    ]
    # 15 of 20 share one era, so an uncapped fill would take most of the budget.
    for index in range(15):
        locators[index]["era"] = "dominant_era"
    snapshot = write_snapshot(tmp_path / "caps", locators)

    policy = SelectionPolicy(
        corpus_id="caps",
        forms=["10-K"],
        base_content_units=10,
        reserve_size=0,
        seed_cik_path="__absent__",
        caps={"era": 0.5},
    )
    result = DeficitSelector(snapshot, policy).select()
    dominant = sum(
        1
        for candidate in result.active_candidates
        if candidate["era"] == "dominant_era"
    )
    assert len(result.active_locators) == 10
    assert dominant <= 5, f"era cap breached: {dominant} of 10"


def test_seed_filers_are_selected_regardless_of_quota(tmp_path: Path) -> None:
    """A declared anchor tenant must appear even if the cap would reject it."""
    locators = [make_locator(index, company_family="megacorp") for index in range(10)]
    snapshot = write_snapshot(tmp_path / "seeds", locators)

    policy = SelectionPolicy(
        corpus_id="seeds",
        forms=["10-K"],
        base_content_units=3,
        reserve_size=0,
        seed_cik_path="__absent__",
    )
    seed_cik = locators[7]["representative_cik"]
    selector = DeficitSelector(
        snapshot,
        policy,
        seed_filers={seed_cik: SeedFiler(cik=seed_cik, seed_group="anchor")},
    )
    result = selector.select()
    selected_ciks = {
        candidate["representative_cik"] for candidate in result.active_candidates
    }
    assert seed_cik in selected_ciks


def test_reserve_is_disjoint_from_the_active_set(
    snapshot_dir: Path, selection_policy: SelectionPolicy
) -> None:
    result = DeficitSelector(snapshot_dir, selection_policy).select()
    assert len(result.reserve_locators) == selection_policy.reserve_size
    assert set(result.active_locators).isdisjoint(result.reserve_locators)


def test_a_zero_reserve_selects_none(tmp_path: Path) -> None:
    locators = [make_locator(index, company_family=f"f{index}") for index in range(10)]
    snapshot = write_snapshot(tmp_path / "noreserve", locators)
    policy = SelectionPolicy(
        corpus_id="noreserve",
        forms=["10-K"],
        base_content_units=3,
        reserve_size=0,
        seed_cik_path="__absent__",
    )
    result = DeficitSelector(snapshot, policy).select()
    assert result.reserve_locators == []


def test_selection_stops_at_the_target_even_when_the_pool_is_larger(
    snapshot_dir: Path,
) -> None:
    policy = SelectionPolicy(
        corpus_id="bounded",
        forms=["10-K"],
        base_content_units=5,
        reserve_size=0,
        seed_cik_path="__absent__",
    )
    result = DeficitSelector(snapshot_dir, policy).select()
    assert len(result.active_locators) == 5


def test_parent_keys_are_retained_and_accounted_for(
    snapshot_dir: Path, selection_policy: SelectionPolicy
) -> None:
    """An expansion must never drop a parent's documents.

    The parent's rows are also loaded into coverage, so the published plan
    reports the quota the combined set actually satisfies rather than only what
    the child added.
    """
    baseline = DeficitSelector(snapshot_dir, selection_policy).select()
    parent = baseline.active_locators[:3]
    result = DeficitSelector(snapshot_dir, selection_policy).select(
        parent_active_keys=parent
    )
    assert result.active_locators[: len(parent)] == parent
    assert len(result.active_locators) == selection_policy.requested_units()
    assert len(result.active_candidates) == len(result.active_locators)


def test_duplicate_parent_keys_are_rejected(
    snapshot_dir: Path, selection_policy: SelectionPolicy
) -> None:
    with pytest.raises(ValueError, match="duplicate locator keys"):
        DeficitSelector(snapshot_dir, selection_policy).select(
            parent_active_keys=["loc-0000", "loc-0000"]
        )


def test_parent_keys_absent_from_the_snapshot_are_rejected(
    snapshot_dir: Path, selection_policy: SelectionPolicy
) -> None:
    with pytest.raises(ValueError, match="absent from the selection snapshot"):
        DeficitSelector(snapshot_dir, selection_policy).select(
            parent_active_keys=["loc-does-not-exist"]
        )


def test_report_names_the_policy_that_produced_it(
    snapshot_dir: Path, selection_policy: SelectionPolicy
) -> None:
    report = DeficitSelector(snapshot_dir, selection_policy).select().report
    assert report["policy_fingerprint"] == selection_policy.policy_fingerprint
    assert report["corpus_id"] == selection_policy.corpus_id
    assert report["level"] == selection_policy.level
    assert report["target_units"] == selection_policy.requested_units()


# --- the global form-by-era allocation --------------------------------------


def _spread_snapshot(root: Path, cells: dict[tuple[str, str], int]) -> Path:
    """One snapshot whose locators occupy the given ``(form, era)`` cells."""
    locators: list[dict[str, Any]] = []
    index = 0
    for (form, era), count in sorted(cells.items()):
        for _ in range(count):
            index += 1
            locators.append(
                make_locator(
                    index,
                    company_family=f"fam{index}",
                    company_name=f"Company {index}",
                    form=form,
                    era=era,
                )
            )
    return write_snapshot(root, locators)


def _allocation_cells(report: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (cell["form"], cell["era"]): cell
        for cell in report["form_era_allocation"]["cells"]
    }


def test_allocation_spreads_a_budget_across_cells(tmp_path: Path) -> None:
    """Two equal cells get equal shares, so the big one does not take both."""
    snapshot = _spread_snapshot(
        tmp_path / "spread", {("10-K", "modern"): 9, ("8-K", "legacy"): 3}
    )
    policy = SelectionPolicy(
        corpus_id="spread",
        forms=["10-K", "8-K"],
        era_bands=[
            EraBand(name="legacy", end_year=2010),
            EraBand(name="modern", start_year=2010),
        ],
        base_content_units=6,
        reserve_size=0,
        seed_cik_path="__absent__",
    )
    result = DeficitSelector(snapshot, policy).select()
    cells = _allocation_cells(result.report)
    assert cells[("10-K", "modern")]["available"] == 9
    assert cells[("8-K", "legacy")]["available"] == 3
    assert cells[("10-K", "modern")]["selected"] == 3
    assert cells[("8-K", "legacy")]["selected"] == 3
    assert result.report["form_era_allocation"]["unallocated"] == 0
    assert result.report["form_era_allocation"]["underfilled_cells"] == 0


def test_allocation_redistributes_from_an_exhausted_cell(tmp_path: Path) -> None:
    """A cell smaller than its share gives the remainder to the others."""
    snapshot = _spread_snapshot(
        tmp_path / "sparse", {("10-K", "modern"): 9, ("8-K", "legacy"): 1}
    )
    policy = SelectionPolicy(
        corpus_id="sparse",
        forms=["10-K", "8-K"],
        era_bands=[
            EraBand(name="legacy", end_year=2010),
            EraBand(name="modern", start_year=2010),
        ],
        base_content_units=6,
        reserve_size=0,
        seed_cik_path="__absent__",
    )
    result = DeficitSelector(snapshot, policy).select()
    cells = _allocation_cells(result.report)
    assert cells[("8-K", "legacy")]["selected"] == 1
    assert cells[("10-K", "modern")]["selected"] == 5
    assert cells[("8-K", "legacy")]["shortfall"] > 0
    assert len(result.active_locators) == 6


def test_a_cap_smaller_than_the_cell_count_prioritizes_era_coverage(
    tmp_path: Path,
) -> None:
    """Three eras, three forms, room for three rows: one row per era.

    Ordering the cells form-first would instead spend all three on whichever form
    sorts first, leaving two eras unrepresented.
    """
    snapshot = _spread_snapshot(
        tmp_path / "eras",
        {
            ("4", "e1"): 5,
            ("4", "e2"): 5,
            ("4", "e3"): 5,
        },
    )
    policy = SelectionPolicy(
        corpus_id="eras",
        forms=["4"],
        era_bands=[
            EraBand(name="e1", start_year=2000, end_year=2001),
            EraBand(name="e2", start_year=2001, end_year=2002),
            EraBand(name="e3", start_year=2002, end_year=2003),
        ],
        base_content_units=3,
        reserve_size=0,
        seed_cik_path="__absent__",
    )
    result = DeficitSelector(snapshot, policy).select()
    selected_eras = {candidate["era"] for candidate in result.active_candidates}
    assert selected_eras == {"e1", "e2", "e3"}


def test_allocation_never_exceeds_the_global_cap(tmp_path: Path) -> None:
    """Floors run first; allocation only draws from what they left."""
    snapshot = _spread_snapshot(
        tmp_path / "shared", {("10-K", "modern"): 20, ("8-K", "legacy"): 20}
    )
    policy = SelectionPolicy(
        corpus_id="shared",
        forms=["10-K", "8-K"],
        era_bands=[
            EraBand(name="legacy", end_year=2010),
            EraBand(name="modern", start_year=2010),
        ],
        base_content_units=5,
        reserve_size=0,
        seed_cik_path="__absent__",
        floors={"era": {"legacy": 4}},
    )
    result = DeficitSelector(snapshot, policy).select()
    assert len(result.active_locators) == 5
    allocation = result.report["form_era_allocation"]
    assert sum(cell["selected"] for cell in allocation["cells"]) == 5
    assert allocation["budget"] + 4 == 5


def test_allocation_reports_an_empty_corpus_rather_than_claiming_balance(
    tmp_path: Path,
) -> None:
    snapshot = write_snapshot(tmp_path / "empty", [])
    policy = SelectionPolicy(
        corpus_id="empty",
        forms=["10-K"],
        era_bands=[EraBand(name="modern", start_year=2010)],
        base_content_units=10,
        reserve_size=0,
        seed_cik_path="__absent__",
    )
    result = DeficitSelector(snapshot, policy).select()
    allocation = result.report["form_era_allocation"]
    assert allocation["cells"] == []
    assert allocation["cell_count"] == 0
    assert allocation["unallocated"] == 10
    assert result.active_locators == []


def test_the_report_names_the_selection_the_run_used(
    snapshot_dir: Path,
) -> None:
    """A reader must not have to re-derive what the plan selected."""
    policy = SelectionPolicy.from_dict(
        {
            **SelectionPolicy(
                corpus_id="reported",
                forms=["10-K"],
                era_bands=[EraBand(name="modern", start_year=2010)],
                base_content_units=4,
                reserve_size=0,
                seed_cik_path="__absent__",
            ).to_dict(),
            "date_selection": [
                {
                    "kind": "recurring",
                    "granularity": "quarter",
                    "values": [1],
                    "start_year": None,
                    "end_year": None,
                }
            ],
        }
    )
    report = DeficitSelector(snapshot_dir, policy).select().report
    assert report["date_selection_text"] == "@Q1"
    assert report["era_band_count"] == 1
    assert report["derives_era_bands"] is False
