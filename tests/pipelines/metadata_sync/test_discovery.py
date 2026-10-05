"""Discovery: which plans exist, how far each got, which snapshot is current."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.pipelines.metadata_sync.discovery import (
    current_snapshot_id,
    describe_roster,
    describe_source,
    list_input_manifests,
    list_plans,
    list_rosters,
    list_snapshots,
    list_source_snapshots,
    plan_summary,
    resolve_input_choice,
    resolve_plan_choice,
    resolve_snapshot_choice,
    resolve_source_choice,
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
    """The shared scanner keys on the filename, so this pipeline names its own."""
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


# ------------------------------------------------------------------- rosters


def _write_registry(
    metadata,
    *,
    registry_id: str = "reg-1",
    ciks: tuple[str, ...] = ("0000001985", "0000001761"),
    source_snapshot_id: str = "src-1",
) -> str:
    """Publish a real registry so discovery reads genuine manifests and digests."""
    from edgar_sec.pipelines.metadata_sync.registry import (
        EFFECTIVE_INPUT_MANIFEST_KIND,
        REGISTRY_SCHEMA_VERSION,
    )
    from edgar_sec.pipelines.metadata_sync.roster import (
        ROSTER_MANIFEST_KIND,
        ROSTER_SCHEMA_VERSION,
        write_roster,
    )

    roster_path = metadata.effective_cik_roster(registry_id)
    roster_path.parent.mkdir(parents=True, exist_ok=True)
    roster = roster_of(ciks)
    digest = write_roster(roster, roster_path)
    roster_path.with_name(roster_path.name + ".manifest.json").write_text(
        json.dumps(
            {
                "manifest_kind": ROSTER_MANIFEST_KIND,
                "schema_version": ROSTER_SCHEMA_VERSION,
                "registry_id": registry_id,
                "artifact_sha256": digest,
                # The loader re-derives the roster id and refuses a mismatch.
                "roster_id": roster.roster_id,
                "row_count": roster.row_count,
            }
        ),
        encoding="utf-8",
    )
    # The effective-input manifest is verified against the CSV's own digest.
    csv_path = metadata.effective_input_file(registry_id)
    csv_path.write_text(
        "".join(f"{cik},name-{cik}\n" for cik in ciks), encoding="utf-8"
    )
    input_manifest = csv_path.with_name(csv_path.name + ".manifest.json")
    input_manifest.write_text(
        json.dumps(
            {
                "manifest_kind": EFFECTIVE_INPUT_MANIFEST_KIND,
                "manifest_schema_version": REGISTRY_SCHEMA_VERSION,
                "registry_id": registry_id,
                "source_snapshot_id": source_snapshot_id,
                "artifact_path": str(csv_path),
                "artifact_sha256": file_sha256(csv_path),
                "curated_cik_count": len(ciks),
                "active_cik_count": len(ciks),
            }
        ),
        encoding="utf-8",
    )
    return registry_id


def test_published_rosters_are_discoverable_with_their_provenance(
    tmp_path: Path,
) -> None:
    """A roster is the durable cohort a comparison publishes; it must be listable."""
    metadata = resolve_metadata_paths(tmp_path)
    _write_registry(metadata)

    found = list_rosters(metadata)
    assert len(found) == 1
    assert found[0]["registry_id"] == "reg-1"
    assert found[0]["readable"] is True
    assert found[0]["row_count"] == 2
    assert found[0]["source_snapshot_id"] == "src-1"


def test_an_unusable_registry_is_listed_with_its_reason(tmp_path: Path) -> None:
    """Hiding it would make a populated directory look like an empty one."""
    metadata = resolve_metadata_paths(tmp_path)
    registry_root = metadata.registry_root("reg-broken")
    registry_root.mkdir(parents=True)

    found = list_rosters(metadata)
    assert [item["registry_id"] for item in found] == ["reg-broken"]
    assert found[0]["readable"] is False
    assert found[0]["readable_reason"]
    assert "unusable" in describe_roster(found[0])


def test_no_registries_lists_nothing(tmp_path: Path) -> None:
    metadata = resolve_metadata_paths(tmp_path)
    assert list_rosters(metadata) == []


def test_a_roster_summary_reads_as_size_and_source(tmp_path: Path) -> None:
    metadata = resolve_metadata_paths(tmp_path)
    _write_registry(metadata)
    described = describe_roster(list_rosters(metadata)[0])
    assert "2 CIKs" in described
    assert "2 active in source" in described
    assert "src-1" in described


# --------------------------------------------------------- source snapshots


def _write_source(
    metadata,
    snapshot_id: str,
    *,
    retrieved_at: str,
    unique_cik_count: int = 4,
    kind: str = "metadata_source_snapshot",
) -> None:
    """Publish a source manifest so discovery reads a real one."""
    path = metadata.source_manifest_file("company_tickers", snapshot_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "manifest_kind": kind,
                "source": "company_tickers",
                "snapshot_id": snapshot_id,
                "retrieved_at": retrieved_at,
                "unique_cik_count": unique_cik_count,
                "listing_row_count": unique_cik_count + 1,
            }
        ),
        encoding="utf-8",
    )


def test_source_snapshots_are_listed_newest_retrieval_first(tmp_path: Path) -> None:
    """A source snapshot's age is the reason it is worth listing at all."""
    metadata = resolve_metadata_paths(tmp_path)
    _write_source(metadata, "older", retrieved_at="2026-01-01T00:00:00Z")
    _write_source(metadata, "newer", retrieved_at="2026-09-30T00:00:00Z")

    found = list_source_snapshots(metadata)

    assert [item["snapshot_id"] for item in found] == ["newer", "older"]
    assert found[0]["retrieved_at"] == "2026-09-30T00:00:00Z"
    assert found[0]["readable"] is True
    assert found[0]["unique_cik_count"] == 4


def test_a_source_summary_names_when_it_was_retrieved(tmp_path: Path) -> None:
    metadata = resolve_metadata_paths(tmp_path)
    _write_source(metadata, "src-1", retrieved_at="2026-09-30T00:00:00Z")
    described = describe_source(list_source_snapshots(metadata)[0])
    assert "retrieved 2026-09-30T00:00:00Z" in described
    assert "4 CIKs" in described


def test_an_unreadable_source_snapshot_is_listed_with_its_reason(
    tmp_path: Path,
) -> None:
    """A damaged source must not read as an absent one."""
    metadata = resolve_metadata_paths(tmp_path)
    _write_source(
        metadata, "foreign", retrieved_at="2026-01-01T00:00:00Z", kind="other"
    )

    found = list_source_snapshots(metadata)

    assert [item["snapshot_id"] for item in found] == ["foreign"]
    assert found[0]["readable"] is False
    assert "unreadable" in describe_source(found[0])


def test_no_source_snapshots_lists_nothing(tmp_path: Path) -> None:
    metadata = resolve_metadata_paths(tmp_path)
    assert list_source_snapshots(metadata) == []


def test_a_source_picker_returns_the_chosen_id(tmp_path: Path) -> None:
    metadata = resolve_metadata_paths(tmp_path)
    _write_source(metadata, "older", retrieved_at="2026-01-01T00:00:00Z")
    _write_source(metadata, "newer", retrieved_at="2026-09-30T00:00:00Z")
    sources = list_source_snapshots(metadata)

    seen: list[str] = []
    chosen = resolve_source_choice(
        sources, select=lambda lines: (seen.extend(lines), "2")[1]
    )

    assert chosen == "older"
    assert len(seen) == 2
    assert "newer" in seen[0]


def test_a_blank_source_picker_cancels(tmp_path: Path) -> None:
    metadata = resolve_metadata_paths(tmp_path)
    _write_source(metadata, "only", retrieved_at="2026-01-01T00:00:00Z")
    assert (
        resolve_source_choice(list_source_snapshots(metadata), select=lambda _: "")
        == ""
    )


# ----------------------------------------------------------- input manifests


def test_input_manifests_are_discovered_with_their_size(tmp_path: Path) -> None:
    """The row count is the only thing separating a seed from an increment."""
    (tmp_path / "cik-sec.csv").write_text(
        "cik,name\n0000001985,ACCEL\n", encoding="utf-8"
    )
    (tmp_path / "delta.csv").write_text("cik,name\n0000001761,TRZ\n", encoding="utf-8")

    found = list_input_manifests(tmp_path)

    assert [item["name"] for item in found] == ["cik-sec.csv", "delta.csv"]
    assert all(item["readable"] for item in found)
    assert found[1]["row_count"] == 1


def test_an_unreadable_input_candidate_is_listed_with_its_reason(
    tmp_path: Path,
) -> None:
    (tmp_path / "broken.csv").write_text("not,a,manifest\n", encoding="utf-8")

    found = list_input_manifests(tmp_path)

    assert [item["name"] for item in found] == ["broken.csv"]
    assert found[0]["readable"] is False
    assert found[0]["readable_reason"]


def test_a_missing_input_directory_lists_nothing(tmp_path: Path) -> None:
    assert list_input_manifests(tmp_path / "absent") == []


def test_an_input_picker_returns_the_chosen_path(tmp_path: Path) -> None:
    (tmp_path / "cik-sec.csv").write_text(
        "cik,name\n0000001985,ACCEL\n", encoding="utf-8"
    )

    chosen = resolve_input_choice(list_input_manifests(tmp_path), select=lambda _: "1")

    assert chosen == str(tmp_path / "cik-sec.csv")


def test_a_blank_input_picker_cancels(tmp_path: Path) -> None:
    (tmp_path / "cik-sec.csv").write_text(
        "cik,name\n0000001985,ACCEL\n", encoding="utf-8"
    )
    assert (
        resolve_input_choice(list_input_manifests(tmp_path), select=lambda _: "") == ""
    )


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
