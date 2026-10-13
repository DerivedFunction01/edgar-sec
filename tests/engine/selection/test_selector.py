"""Deficit fill: classification caps, floors, cell allocation, and accounting."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.engine.selection.cell_allocation import equalized_cell_targets
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
from edgar_sec.engine.selection.source import CandidateSource
from tests.engine.selection.conftest import (
    make_dominant_snapshot,
    make_locator,
    write_snapshot,
)


def test_selection_fills_the_target_and_reports_itself(
    snapshot_dir: Path, selection_policy: SelectionPolicy
) -> None:
    events: list[dict[str, Any]] = []
    result = DeficitSelector(snapshot_dir, selection_policy).select(
        progress=events.append
    )

    assert result.active_count == selection_policy.requested_units()
    stages = [event["stage"] for event in events]
    assert stages.index("selection_seeds") < stages.index("selection_form_era")
    assert "selection_form_era_staging_started" in stages
    staging = next(
        event
        for event in events
        if event["stage"] == "selection_form_era_availability_complete"
    )
    assert staging["rows"] > 0
    assert "selection_form_era_staging_complete" in stages
    assert not any(stage.startswith("selection_form_era_round_") for stage in stages)
    assert "selection_form_era_complete" in stages
    assert stages.index("selection_form_era_complete") < stages.index(
        "selection_weighted"
    )
    assert sum(1 for _ in result.active_candidates) == result.active_count
    assert result.report["active_occurrences_count"] >= result.active_count
    assert result.report["active_locators_count"] == result.active_count
    assert "coverage_distributions" not in result.report


def test_selection_is_deterministic_for_one_seed(
    snapshot_dir: Path, selection_policy: SelectionPolicy
) -> None:
    """A rerun picking different documents would make the plan a claim, not a record."""
    first = DeficitSelector(snapshot_dir, selection_policy).select()
    second = DeficitSelector(snapshot_dir, selection_policy).select()
    assert list(first.active_locators) == list(second.active_locators)
    assert first.report == second.report


def test_form_era_selection_does_not_issue_a_pool_query_per_cell(
    snapshot_dir: Path,
    selection_policy: SelectionPolicy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_cell_query(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("form/era allocation must consume the staged candidate relation")

    monkeypatch.setattr(CandidateSource, "pool_for_cell", reject_cell_query)
    result = DeficitSelector(snapshot_dir, selection_policy).select()
    assert result.active_count == selection_policy.requested_units()


def test_selection_scratch_database_is_removed_with_result(
    snapshot_dir: Path, selection_policy: SelectionPolicy
) -> None:
    result = DeficitSelector(snapshot_dir, selection_policy).select()
    state_dir = result.active_keys_path.parent
    assert (state_dir / "selection.duckdb").is_file()
    result.close()
    assert not state_dir.exists()


def test_a_different_seed_selects_differently(
    snapshot_dir: Path, selection_policy: SelectionPolicy
) -> None:
    """The seed is the tie-break, so it must actually reach the ordering."""
    other = SelectionPolicy(
        corpus_id=selection_policy.corpus_id,
        forms=selection_policy.forms,
        base_content_units=selection_policy.requested_units(),
        reserve_size=selection_policy.reserve_size,
        seed="a-completely-different-seed",
    )
    baseline = DeficitSelector(snapshot_dir, selection_policy).select()
    seeded = DeficitSelector(snapshot_dir, other).select()
    assert list(baseline.active_locators) != list(seeded.active_locators)


def test_a_dominant_family_cannot_fill_the_selection(
    dominant_family_snapshot: Path,
) -> None:
    """Every locator shares one signature but for the family name, so an uncapped
    fill would take all twelve.
    """
    policy = SelectionPolicy(
        corpus_id="dominant",
        forms=["10-K"],
        base_content_units=8,
        reserve_size=0,
    )
    result = DeficitSelector(dominant_family_snapshot, policy).select()

    families = [candidate["company_family"] for candidate in result.active_candidates]
    assert result.active_count == 8
    assert families.count("megacorp") == 1, "family cap did not hold"
    assert len(set(families)) == 8, (
        "selection collapsed onto fewer entities than available"
    )


def test_the_cap_is_what_bounds_dominance(tmp_path: Path) -> None:
    """Paired with the dominant-family case: the cap is the binding constraint, not
    pool ordering.
    """
    snapshot = make_dominant_snapshot(tmp_path / "lifted", others=3)

    def select(cap: int) -> list[str]:
        policy = SelectionPolicy(
            corpus_id="lifted",
            forms=["10-K"],
            base_content_units=10,
            reserve_size=0,
            max_per_company_classification=cap,
        )
        result = DeficitSelector(snapshot, policy).select()
        return [candidate["company_family"] for candidate in result.active_candidates]

    # Twelve megacorp locators in one signature plus three others: a cap of one admits
    # at most four candidates.
    capped = select(1)
    assert len(capped) == 4
    assert capped.count("megacorp") == 1

    uncapped = select(12)
    assert len(uncapped) == 10
    assert uncapped.count("megacorp") > 1


def test_an_unreachable_target_is_reported_as_a_shortfall(
    tmp_path: Path,
) -> None:
    """The report must expose a shortfall, or a published plan asserts a quota it
    never met.
    """
    snapshot = make_dominant_snapshot(tmp_path / "short", others=3)
    policy = SelectionPolicy(
        corpus_id="short",
        forms=["10-K"],
        base_content_units=10,
        reserve_size=0,
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
    )
    result = DeficitSelector(dominant_family_snapshot, policy).select()
    assert result.report["form_era_allocation"]["cap_rejected_candidates"] > 0
    assert result.report["unique_company_families"] == 8


def test_classification_signature_has_six_dimensions() -> None:
    assert len(CLASSIFICATION_DIMENSIONS) == 6
    assert CLASSIFICATION_DIMENSIONS[0] == "company_family"


def test_classification_signature_caps_on_the_resolved_family() -> None:
    """`company_family` already carries the name fallback from the build, so the
    signature reads it directly rather than re-resolving.
    """
    candidate = {
        "company_family": "Example Co",
        "form": "10-K",
        "era": "modern",
        "sic_code": "3571",
        "entity_type": "operating",
        "lifecycle_class": "active",
    }
    assert classification_signature(candidate)[0] == "example co"


def test_classification_signature_keeps_an_empty_family_distinct() -> None:
    """An unmatched registrant resolves to `''`, which must stay distinct from the
    `none` a genuinely absent value produces.
    """
    candidate = {
        "company_family": "",
        "form": "10-K",
        "era": "modern",
        "sic_code": "3571",
        "entity_type": "operating",
        "lifecycle_class": "active",
    }
    assert classification_signature(candidate)[0] == ""


def test_floors_are_satisfied_before_the_weighted_fill(
    snapshot_dir: Path, selection_policy: SelectionPolicy
) -> None:
    policy = SelectionPolicy(
        corpus_id="floors",
        forms=["10-K"],
        era_bands=[
            EraBand(name="historical", end_year=2010),
            EraBand(name="modern", start_year=2010),
        ],
        base_content_units=8,
        reserve_size=0,
        floors={"era": {"historical": 4}},
    )
    result = DeficitSelector(snapshot_dir, policy).select()
    assert (
        sum(candidate["era"] == "historical" for candidate in result.active_candidates)
        >= 4
    )
    assert result.report["underfilled_floors"] == {}


def test_exhibit_like_floor_counts_unique_accessions(tmp_path: Path) -> None:
    locators = [
        make_locator(
            0,
            primary_exhibit_like=True,
            representative_accession="shared-accession",
            company_family="first-family",
        ),
        make_locator(
            1,
            primary_exhibit_like=True,
            representative_accession="shared-accession",
            company_family="second-family",
        ),
        make_locator(
            2,
            primary_exhibit_like=True,
            representative_accession="other-accession",
            company_family="third-family",
        ),
        make_locator(3, primary_exhibit_like=False, company_family="fourth-family"),
    ]
    snapshot = write_snapshot(tmp_path / "exhibit-floor", locators)
    policy = SelectionPolicy(
        corpus_id="exhibit-floor",
        forms=["10-K"],
        base_content_units=2,
        reserve_size=0,
        floors={"primary_exhibit_like": {"true": 2}},
    )

    result = DeficitSelector(snapshot, policy).select()

    assert result.active_count == 2
    assert (
        sum(
            candidate["primary_exhibit_like"] is True
            for candidate in result.active_candidates
        )
        == 2
    )
    assert result.report["underfilled_floors"] == {}


def test_exhibit_like_floor_reports_distinct_accession_shortfall(
    tmp_path: Path,
) -> None:
    locators = [
        make_locator(
            0,
            primary_exhibit_like=True,
            representative_accession="one-accession",
            company_family="first-family",
        ),
        make_locator(
            1,
            primary_exhibit_like=True,
            representative_accession="one-accession",
            company_family="second-family",
        ),
    ]
    snapshot = write_snapshot(tmp_path / "exhibit-shortfall", locators)
    policy = SelectionPolicy(
        corpus_id="exhibit-shortfall",
        forms=["10-K"],
        base_content_units=2,
        reserve_size=0,
        floors={"primary_exhibit_like": {"true": 2}},
    )

    result = DeficitSelector(snapshot, policy).select()

    assert result.report["underfilled_floors"]["primary_exhibit_like"]["true"] == {
        "required": 2,
        "selected": 1,
        "deficit": 1,
    }


def test_an_impossible_floor_is_reported_not_silently_ignored(
    snapshot_dir: Path,
) -> None:
    """Otherwise the plan publishes with an unmet quota the reader cannot see."""
    policy = SelectionPolicy(
        corpus_id="impossible",
        forms=["10-K"],
        era_bands=[EraBand(name="modern", start_year=2010)],
        base_content_units=4,
        reserve_size=0,
        floors={"era": {"ancient": 3}},
    )
    result = DeficitSelector(snapshot_dir, policy).select()
    underfilled = result.report["underfilled_floors"]["era"]["ancient"]
    assert underfilled == {"required": 3, "selected": 0, "deficit": 3}
    assert result.active_count == 4


def test_composites_are_satisfied_before_single_dimension_floors(
    tmp_path: Path,
) -> None:
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
        floors={"era": {"common": 2}},
        composites=[{"filters": {"form": "20-F", "era": "rare"}, "min": 2}],
    )
    result = DeficitSelector(snapshot, policy).select()
    chosen = {candidate["form"] for candidate in result.active_candidates}
    assert "20-F" in chosen, "the composite stratum was not satisfied"


def test_caps_bound_a_dimensions_share_of_the_target(tmp_path: Path) -> None:
    locators = [
        make_locator(index, company_family=f"fam{index}") for index in range(20)
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
        caps={"era": 0.5},
    )
    result = DeficitSelector(snapshot, policy).select()
    dominant = sum(
        1
        for candidate in result.active_candidates
        if candidate["era"] == "dominant_era"
    )
    assert result.active_count == 10
    assert dominant <= 5, f"era cap breached: {dominant} of 10"


def test_seed_filers_are_selected_regardless_of_quota(tmp_path: Path) -> None:
    locators = [make_locator(index, company_family="megacorp") for index in range(10)]
    snapshot = write_snapshot(tmp_path / "seeds", locators)

    policy = SelectionPolicy(
        corpus_id="seeds",
        forms=["10-K"],
        base_content_units=3,
        reserve_size=0,
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
    assert result.reserve_count == selection_policy.reserve_size
    assert set(result.active_locators).isdisjoint(result.reserve_locators)


def test_a_zero_reserve_selects_none(tmp_path: Path) -> None:
    locators = [make_locator(index, company_family=f"f{index}") for index in range(10)]
    snapshot = write_snapshot(tmp_path / "noreserve", locators)
    policy = SelectionPolicy(
        corpus_id="noreserve",
        forms=["10-K"],
        base_content_units=3,
        reserve_size=0,
    )
    result = DeficitSelector(snapshot, policy).select()
    assert list(result.reserve_locators) == []


def test_selection_stops_at_the_target_even_when_the_pool_is_larger(
    snapshot_dir: Path,
) -> None:
    policy = SelectionPolicy(
        corpus_id="bounded",
        forms=["10-K"],
        base_content_units=5,
        reserve_size=0,
    )
    result = DeficitSelector(snapshot_dir, policy).select()
    assert result.active_count == 5


def test_parent_keys_are_retained_and_accounted_for(
    snapshot_dir: Path, selection_policy: SelectionPolicy, tmp_path: Path
) -> None:
    """The parent's rows also load into coverage, so the report accounts for the
    combined set rather than only what the child added.
    """
    baseline = DeficitSelector(snapshot_dir, selection_policy).select()
    parent = list(baseline.active_locators)[:3]
    parent_path = _write_parent_keys(tmp_path / "parent.parquet", parent)
    result = DeficitSelector(snapshot_dir, selection_policy).select(
        parent_locator_path=parent_path
    )
    assert set(parent) <= set(result.active_locators)
    assert result.active_count == selection_policy.requested_units()
    assert sum(1 for _ in result.active_candidates) == result.active_count


def test_duplicate_parent_keys_are_rejected(
    snapshot_dir: Path, selection_policy: SelectionPolicy, tmp_path: Path
) -> None:
    parent_path = _write_parent_keys(
        tmp_path / "duplicate-parent.parquet", ["loc-0000", "loc-0000"]
    )
    with pytest.raises(ValueError, match="duplicate locator keys"):
        DeficitSelector(snapshot_dir, selection_policy).select(
            parent_locator_path=parent_path
        )


def test_parent_keys_absent_from_the_snapshot_are_rejected(
    snapshot_dir: Path, selection_policy: SelectionPolicy, tmp_path: Path
) -> None:
    parent_path = _write_parent_keys(
        tmp_path / "missing-parent.parquet", ["loc-does-not-exist"]
    )
    with pytest.raises(ValueError, match="absent from the selection snapshot"):
        DeficitSelector(snapshot_dir, selection_policy).select(
            parent_locator_path=parent_path
        )


def test_report_names_the_policy_that_produced_it(
    snapshot_dir: Path, selection_policy: SelectionPolicy
) -> None:
    report = DeficitSelector(snapshot_dir, selection_policy).select().report
    assert report["policy_fingerprint"] == selection_policy.policy_fingerprint
    assert report["corpus_id"] == selection_policy.corpus_id
    assert report["level"] == selection_policy.level
    assert report["target_units"] == selection_policy.requested_units()


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


def test_equalized_targets_account_for_prefilled_cells() -> None:
    targets = equalized_cell_targets(
        [
            ("10-K", "modern", 4, 12),
            ("8-K", "historical", 0, 20),
            ("S-1", "modern", 2, 0),
        ],
        4,
    )
    assert targets == {
        ("10-K", "modern"): 4,
        ("8-K", "historical"): 4,
        ("S-1", "modern"): 2,
    }


def test_equalized_targets_saturate_capacity_and_break_ties_in_order() -> None:
    targets = equalized_cell_targets(
        [
            ("10-K", "early", 0, 1),
            ("10-K", "late", 0, 10),
            ("8-K", "late", 0, 10),
        ],
        5,
    )
    assert targets == {
        ("10-K", "early"): 1,
        ("10-K", "late"): 2,
        ("8-K", "late"): 2,
    }


def _write_parent_keys(path: Path, keys: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({"document_locator_key": keys}), path)
    return path


def test_allocation_spreads_a_budget_across_cells(tmp_path: Path) -> None:
    """Two equal cells get equal shares, so the big one does not take both."""
    snapshot = _spread_snapshot(
        tmp_path / "spread", {("10-K", "modern"): 9, ("8-K", "historical"): 3}
    )
    policy = SelectionPolicy(
        corpus_id="spread",
        forms=["10-K", "8-K"],
        era_bands=[
            EraBand(name="historical", end_year=2010),
            EraBand(name="modern", start_year=2010),
        ],
        base_content_units=6,
        reserve_size=0,
    )
    result = DeficitSelector(snapshot, policy).select()
    cells = _allocation_cells(result.report)
    assert cells[("10-K", "modern")]["available"] == 9
    assert cells[("8-K", "historical")]["available"] == 3
    assert cells[("10-K", "modern")]["selected"] == 3
    assert cells[("8-K", "historical")]["selected"] == 3
    assert result.report["form_era_allocation"]["unallocated"] == 0
    assert result.report["form_era_allocation"]["underfilled_cells"] == 0


def test_allocation_redistributes_from_an_exhausted_cell(tmp_path: Path) -> None:
    """A cell smaller than its share gives the remainder to the others."""
    snapshot = _spread_snapshot(
        tmp_path / "sparse", {("10-K", "modern"): 9, ("8-K", "historical"): 1}
    )
    policy = SelectionPolicy(
        corpus_id="sparse",
        forms=["10-K", "8-K"],
        era_bands=[
            EraBand(name="historical", end_year=2010),
            EraBand(name="modern", start_year=2010),
        ],
        base_content_units=6,
        reserve_size=0,
    )
    result = DeficitSelector(snapshot, policy).select()
    cells = _allocation_cells(result.report)
    assert cells[("8-K", "historical")]["selected"] == 1
    assert cells[("10-K", "modern")]["selected"] == 5
    assert cells[("8-K", "historical")]["eligible_capacity"] == 1
    assert cells[("8-K", "historical")]["target"] == 1
    assert cells[("8-K", "historical")]["shortfall"] == 0
    assert result.active_count == 6


def test_a_cap_smaller_than_the_cell_count_prioritizes_era_coverage(
    tmp_path: Path,
) -> None:
    """Ordering the cells form-first would instead spend all three rows on whichever
    form sorts first, leaving two eras unrepresented.
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
    )
    result = DeficitSelector(snapshot, policy).select()
    selected_eras = {candidate["era"] for candidate in result.active_candidates}
    assert selected_eras == {"e1", "e2", "e3"}


def test_allocation_never_exceeds_the_global_cap(tmp_path: Path) -> None:
    """Floors run first; allocation only draws from what they left."""
    snapshot = _spread_snapshot(
        tmp_path / "shared", {("10-K", "modern"): 20, ("8-K", "historical"): 20}
    )
    policy = SelectionPolicy(
        corpus_id="shared",
        forms=["10-K", "8-K"],
        era_bands=[
            EraBand(name="historical", end_year=2010),
            EraBand(name="modern", start_year=2010),
        ],
        base_content_units=5,
        reserve_size=0,
        floors={"era": {"historical": 4}},
    )
    result = DeficitSelector(snapshot, policy).select()
    assert result.active_count == 5
    allocation = result.report["form_era_allocation"]
    assert sum(cell["selected"] for cell in allocation["cells"]) == 5
    assert allocation["budget"] + 4 == 5
    cells = _allocation_cells(result.report)
    assert cells[("8-K", "historical")]["starting_selected"] == 4
    assert cells[("10-K", "modern")]["target"] == 1


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
    )
    result = DeficitSelector(snapshot, policy).select()
    allocation = result.report["form_era_allocation"]
    assert allocation["cells"] == []
    assert allocation["cell_count"] == 0
    assert allocation["unallocated"] == 10
    assert list(result.active_locators) == []


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
