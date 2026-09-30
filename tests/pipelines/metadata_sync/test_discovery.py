"""Discovery tests: what the operator can be told is already on disk.

These cover the surface v1's wizard had and v2's lost -- an operator can see
which plans exist, how far each got, which snapshot is current, and pick from a
numbered list. Every case is offline and reads only manifests.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edgar_sec.pipelines.metadata_sync.discovery import (
    current_snapshot_id,
    list_plans,
    list_snapshots,
    plan_summary,
    resolve_plan_choice,
)
from edgar_sec.pipelines.metadata_sync.manifest import read_cik_manifest
from edgar_sec.pipelines.metadata_sync.paths import resolve_metadata_paths
from edgar_sec.pipelines.metadata_sync.planner import build_plan, write_plan
from edgar_sec.pipelines.metadata_sync.roster import roster_from_manifest
from tests.support import fixture_path


def _write_plan(
    metadata,
    *,
    chunk_size: int = 2,
    roster_ciks: tuple[str, ...] = (),
) -> str:
    """Write a real plan bundle so discovery reads genuine manifests."""
    from dataclasses import replace

    from edgar_sec.pipelines.metadata_sync.paths import resolve_run_paths

    manifest = read_cik_manifest(fixture_path("cik_sec_mini.csv"))
    if roster_ciks:
        manifest = replace(manifest, ciks=roster_ciks, names=("",) * len(roster_ciks))
    plan = build_plan(roster_from_manifest(manifest), chunk_size=chunk_size)
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
    manifest_path = metadata.snapshot_manifest(plan_id)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps({"snapshot_id": plan_id}), encoding="utf-8")

    assert plan_summary(metadata, plan_id)["published"] is True


def test_current_snapshot_is_read_from_the_pointer(tmp_path: Path) -> None:
    metadata = resolve_metadata_paths(tmp_path)
    pointer = metadata.current_pointer
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text('{"snapshot_id": "abc123"}', encoding="utf-8")
    assert current_snapshot_id(metadata) == "abc123"


def test_an_unreadable_pointer_is_not_fatal(tmp_path: Path) -> None:
    metadata = resolve_metadata_paths(tmp_path)
    pointer = metadata.current_pointer
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text("not json", encoding="utf-8")
    assert current_snapshot_id(metadata) == ""


def test_list_snapshots_uses_this_pipeline_manifest_name(tmp_path: Path) -> None:
    """The shared scanner takes the manifest filename; Phase 1 names its own."""
    metadata = resolve_metadata_paths(tmp_path)
    good = metadata.snapshot_dir("good")
    good.mkdir(parents=True)
    (good / "metadata.manifest.json").write_text(
        '{"snapshot_id": "good", "row_count": 3}', encoding="utf-8"
    )
    damaged = metadata.snapshot_dir("damaged")
    damaged.mkdir(parents=True)
    (damaged / "metadata.manifest.json").write_text("not json", encoding="utf-8")
    # A document_storage-shaped manifest must not be mistaken for a Phase 1 one.
    foreign = metadata.snapshot_dir("foreign")
    foreign.mkdir(parents=True)
    (foreign / "manifest.json").write_text(
        '{"snapshot_id": "foreign"}', encoding="utf-8"
    )

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
    # Index by position rather than assuming an order this test does not own;
    # ordering is covered by test_list_plans_is_newest_first.
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
