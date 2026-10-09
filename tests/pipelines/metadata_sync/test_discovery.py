"""Discovery: which plans exist, how far each got, which snapshot is current."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.manifest import (
    DAGNodeManifest,
    PartDescriptor,
)
from edgar_sec.pipelines.metadata_sync.discovery import (
    current_snapshot_id,
    list_plans,
    list_snapshots,
    plan_summary,
    resolve_plan_choice,
    resolve_snapshot_choice,
)
from edgar_sec.pipelines.metadata_sync.paths import resolve_metadata_paths
from edgar_sec.pipelines.metadata_sync.planner import build_plan, write_plan
from tests.support import fixture_cohort, roster_of


def _write_plan(
    metadata,
    *,
    chunk_size: int = 2,
    roster_ciks: tuple[str, ...] = (),
) -> str:
    """Write a real plan bundle so discovery reads genuine manifests."""

    from edgar_sec.pipelines.metadata_sync.paths import resolve_run_paths

    if roster_ciks:
        plan = build_plan(roster_of(tuple(roster_ciks)), chunk_size=chunk_size)
    else:
        plan = build_plan(
            fixture_cohort("cik_sec_mini.csv").roster, chunk_size=chunk_size
        )
    write_plan(plan, resolve_run_paths(plan.plan_id, metadata.artifacts_root))
    return plan.plan_id


def test_empty_tree_lists_nothing(tmp_path: Path) -> None:
    metadata = resolve_metadata_paths(tmp_path)
    assert list_plans(metadata) == []
    assert list_snapshots(metadata) == []
    assert current_snapshot_id(metadata) == ""


def test_plan_summary_reports_size_and_progress(tmp_path: Path) -> None:
    metadata = resolve_metadata_paths(tmp_path)
    plan_id = _write_plan(metadata, chunk_size=2)

    summary = plan_summary(metadata, plan_id)
    assert summary["plan_id"] == plan_id
    assert summary["row_count"] == 4
    assert summary["chunk_count"] == 2
    assert summary["chunk_size"] == 2
    assert summary["completed_chunks"] == 0
    assert summary["published"] is False
    assert summary["readable"] is True


def test_list_plans_is_newest_first(tmp_path: Path) -> None:
    metadata = resolve_metadata_paths(tmp_path)
    first = _write_plan(metadata, chunk_size=4, roster_ciks=("0000001985",))
    second = _write_plan(
        metadata, chunk_size=2, roster_ciks=("0000001985", "0000001761")
    )
    third = _write_plan(metadata, chunk_size=1, roster_ciks=("0000000020",))

    listed = [item["plan_id"] for item in list_plans(metadata)]
    assert set(listed) == {first, second, third}
    assert listed[0] == third


def test_an_unreadable_plan_still_lists_with_unknown_progress(tmp_path: Path) -> None:
    """Discovery reports what it can; it never hides a directory it cannot load."""
    metadata = resolve_metadata_paths(tmp_path)
    plan_id = _write_plan(metadata, chunk_size=2)
    (metadata.plan_dir(plan_id) / "plan.json").write_text("not json", encoding="utf-8")

    summary = plan_summary(metadata, plan_id)
    assert summary["readable"] is False
    assert summary["completed_chunks"] == -1
    assert summary["row_count"] == 0
    assert [item["plan_id"] for item in list_plans(metadata)] == [plan_id]


def test_a_version_incompatible_plan_is_reported_not_hidden(tmp_path: Path) -> None:
    import json

    metadata = resolve_metadata_paths(tmp_path)
    plan_id = _write_plan(metadata, chunk_size=2)
    manifest_path = metadata.plan_dir(plan_id) / "plan.json"
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw["plan_format_version"] = "99.0.0"
    manifest_path.write_text(json.dumps(raw), encoding="utf-8")

    summary = plan_summary(metadata, plan_id)
    assert summary["readable"] is True
    assert summary["completed_chunks"] == -1


def test_published_plan_is_flagged(tmp_path: Path) -> None:
    metadata = resolve_metadata_paths(tmp_path)
    plan_id = _write_plan(metadata, chunk_size=2)
    DAGCatalog(metadata.snapshots_root).record_node(
        DAGNodeManifest(
            snapshot_id=plan_id,
            kind="checkpoint",
            parents=(),
            checkpoint_anchor_id=plan_id,
            lineage_depth=0,
            created_at="2026-10-07T00:00:00Z",
            relations={
                "submissions": (PartDescriptor("parts/data.parquet", "sha", 1, 1),)
            },
            logical_fingerprint="fp-plan",
        )
    )

    assert plan_summary(metadata, plan_id)["published"] is True


def test_current_snapshot_is_read_from_the_pointer(tmp_path: Path) -> None:
    metadata = resolve_metadata_paths(tmp_path)
    catalog = DAGCatalog(metadata.snapshots_root)
    catalog.write_pointer("main", "abc123")
    assert current_snapshot_id(metadata) == "abc123"


def test_an_unreadable_pointer_is_not_fatal(tmp_path: Path) -> None:
    metadata = resolve_metadata_paths(tmp_path)
    assert current_snapshot_id(metadata) == ""


def test_list_snapshots_from_catalog(tmp_path: Path) -> None:
    metadata = resolve_metadata_paths(tmp_path)
    assert list_snapshots(metadata) == []
    catalog = DAGCatalog(metadata.snapshots_root)
    manifest = DAGNodeManifest(
        snapshot_id="good",
        kind="checkpoint",
        parents=(),
        checkpoint_anchor_id="good",
        lineage_depth=0,
        created_at="2026-10-07T00:00:00Z",
        relations={
            "submissions": (PartDescriptor("good/parts/data.parquet", "sha", 10, 12),)
        },
        logical_fingerprint="fp-good",
    )
    catalog.record_node(manifest)
    found = list_snapshots(metadata)
    assert [item["snapshot_id"] for item in found] == ["good"]


def test_single_plan_is_chosen_without_asking(tmp_path: Path) -> None:
    metadata = resolve_metadata_paths(tmp_path)
    plan_id = _write_plan(metadata, chunk_size=2)
    plans = list_plans(metadata)

    def must_not_be_called(_lines: list[str]) -> str:
        raise AssertionError("a lone plan should not prompt")

    assert resolve_plan_choice(plans, select=must_not_be_called)["plan_id"] == plan_id


def test_several_plans_render_and_pick_by_number(tmp_path: Path) -> None:
    metadata = resolve_metadata_paths(tmp_path)
    _write_plan(metadata, chunk_size=4, roster_ciks=("0000001985",))
    second = _write_plan(
        metadata, chunk_size=2, roster_ciks=("0000001985", "0000001761")
    )
    plans = list_plans(metadata)
    # Ordering is covered by test_list_plans_is_newest_first.
    target = next(
        str(index)
        for index, plan in enumerate(plans, start=1)
        if plan["plan_id"] == second
    )

    captured: list[str] = []

    def picker(lines: list[str]) -> str:
        captured.extend(lines)
        return target

    chosen = resolve_plan_choice(plans, select=picker)
    assert chosen is not None and chosen["plan_id"] == second
    assert len(captured) == 2
    assert all(line.startswith("  ") for line in captured)
    assert "CIKs" in captured[0]
    assert "0/1 done" in captured[0]


@pytest.mark.parametrize("answer", ["", "0", "99", "not-a-number"])
def test_a_bad_or_cancelled_pick_returns_nothing(tmp_path: Path, answer: str) -> None:
    metadata = resolve_metadata_paths(tmp_path)
    _write_plan(metadata, chunk_size=4, roster_ciks=("0000001985",))
    _write_plan(metadata, chunk_size=2, roster_ciks=("0000001985", "0000001761"))

    chosen = resolve_plan_choice(list_plans(metadata), select=lambda _lines: answer)
    assert chosen is None


def test_no_plans_means_nothing_to_choose(tmp_path: Path) -> None:
    metadata = resolve_metadata_paths(tmp_path)
    assert list_plans(metadata) == []
    assert resolve_plan_choice([], select=lambda _lines: "1") is None


# ----------------------------------------------------------------- snapshots


def test_snapshots_render_with_size_lineage_and_the_current_marker(
    tmp_path: Path,
) -> None:
    manifests = [
        {
            "snapshot_id": "newer",
            "row_count": 1200,
            "parts": [{"path": "a"}, {"path": "b"}],
            "kind": "full",
        },
        {
            "snapshot_id": "older",
            "row_count": 900,
            "kind": "delta",
            "parent_snapshot_id": "base-1",
        },
    ]
    captured: list[str] = []
    chosen = resolve_snapshot_choice(
        manifests, "newer", select=lambda lines: captured.extend(lines) or "2"
    )
    assert chosen == "older"
    assert "[current]" in captured[0] and "2 parts" in captured[0]
    assert "1,200 rows" in captured[0]
    assert "augments base-1" in captured[1] and "delta" in captured[1]


@pytest.mark.parametrize("answer", ["", "0", "5", "nope"])
def test_a_kept_or_invalid_snapshot_choice_returns_nothing(answer: str) -> None:
    manifests = [{"snapshot_id": "only", "row_count": 1}]
    assert (
        resolve_snapshot_choice(manifests, "only", select=lambda _lines: answer) == ""
    )


def test_no_snapshots_means_nothing_to_choose() -> None:
    assert resolve_snapshot_choice([], "", select=lambda _lines: "1") == ""


# ------------------------------------------------------------------ plan kind


def test_a_delta_plan_is_labelled_as_one_in_the_picker(tmp_path: Path) -> None:
    """Rendering both plan kinds alike hides which ones are safe to merge."""
    metadata = resolve_metadata_paths(tmp_path)
    cohort = fixture_cohort("cik_sec_mini.csv")
    from edgar_sec.pipelines.metadata_sync.paths import resolve_run_paths

    delta = build_plan(
        cohort.roster,
        chunk_size=2,
        kind="delta",
        parent_id="base-snap",
    )
    write_plan(delta, resolve_run_paths(delta.plan_id, metadata.artifacts_root))
    full = build_plan(cohort.roster, chunk_size=2)
    write_plan(full, resolve_run_paths(full.plan_id, metadata.artifacts_root))

    summaries = [plan_summary(metadata, plan.plan_id) for plan in (full, delta)]
    assert summaries[0]["kind"] != "delta"
    assert summaries[1]["kind"] == "delta"
    assert summaries[1]["parent_snapshot_id"] == "base-snap"

    # Two plans, so the picker renders rather than auto-adopting the only one.
    lines: list[str] = []
    resolve_plan_choice(
        summaries, select=lambda rendered: (lines.extend(rendered), "1")[1]
    )

    assert "delta on base-snap" in lines[1]
    assert "delta" not in lines[0]
