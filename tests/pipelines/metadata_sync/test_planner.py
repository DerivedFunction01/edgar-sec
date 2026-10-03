"""Deterministic planning, persistence, and staleness tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edgar_sec.domain.submissions.schemas import SCHEMA_VERSION
from edgar_sec.pipelines.metadata_sync.options import derive_plan_id, plan_options
from edgar_sec.pipelines.metadata_sync.paths import resolve_run_paths
from edgar_sec.pipelines.metadata_sync.planner import (
    PLAN_FORMAT_VERSION,
    build_plan,
    load_plan,
    utc_now_iso,
    write_plan,
)
from edgar_sec.pipelines.metadata_sync.planner import (
    derive_plan_id as derive_plan_id_direct,
)
from edgar_sec.pipelines.metadata_sync.roster import RosterError
from tests.support import compiled_cohort, fixture_cohort, fixture_path, roster_of


def _plan(**kwargs):
    return build_plan(fixture_cohort("cik_sec_mini.csv").roster, **kwargs)


def test_chunks_are_ordinal_ranges_not_embedded_lists() -> None:
    plan = _plan(chunk_size=2)
    assert plan.row_count == 4
    assert plan.chunk_count == 2
    assert plan.chunk_start(0) == 0 and plan.chunk_length(0) == 2
    assert plan.chunk_start(1) == 2 and plan.chunk_length(1) == 2
    assert plan.chunk_ciks(0) == ("0000001985", "0000001761")
    assert plan.chunk_ciks(1) == ("0000000020", "0000037996")


def test_the_last_chunk_is_short() -> None:
    plan = _plan(chunk_size=3)
    assert plan.chunk_count == 2
    assert plan.chunk_length(1) == 1
    assert plan.chunk_ciks(1) == ("0000037996",)


def test_chunk_ids_are_contiguous_and_ascending() -> None:
    assert _plan(chunk_size=2).chunk_ids() == [0, 1]


def test_plan_manifest_does_not_grow_with_the_cohort() -> None:
    """The whole point: the document is constant in cohort size.

    The previous format stored the CIK list three times, so a 250,000-CIK cohort
    produced a 15 MB plan. The manifest now records the roster identity and the
    chunk layout, and the cohort itself lives beside it.
    """
    small = json.dumps(_plan(chunk_size=2).to_manifest(), indent=2)
    large = build_plan(
        roster_of(tuple(f"{value:010d}" for value in range(1, 250_001))),
        chunk_size=1000,
    )
    assert len(json.dumps(large.to_manifest(), indent=2)) < 2 * len(small)


def test_plan_is_deterministic_across_runs() -> None:
    first = _plan(chunk_size=2, created_at="2026-01-01T00:00:00Z")
    second = _plan(chunk_size=2, created_at="2026-01-02T00:00:00Z")
    assert first.plan_id == second.plan_id
    assert first.created_at != second.created_at


def test_plan_id_changes_with_chunking() -> None:
    assert _plan(chunk_size=2).plan_id != _plan(chunk_size=3).plan_id


def test_plan_id_ignores_assignment() -> None:
    """Reassigning workers must not move the plan directory.

    Assignment is a separate artifact with its own identity, so changing the worker
    configuration cannot discard every completed checkpoint for an identical
    cohort.
    """
    assert derive_plan_id_direct(roster_of(("0000001985",)).roster_id, 1000) == (
        derive_plan_id_direct(roster_of(("0000001985",)).roster_id, 1000)
    )
    manifest = _plan(chunk_size=2).to_manifest()
    assert "partition_count" not in manifest
    assert "worker" not in json.dumps(manifest)


def test_delta_plans_bind_to_their_base_snapshot() -> None:
    roster = roster_of(("0000001985", "0000001761"))
    against_a = derive_plan_id_direct(
        roster.roster_id, 2, kind="delta", parent_id="base-a"
    )
    against_b = derive_plan_id_direct(
        roster.roster_id, 2, kind="delta", parent_id="base-b"
    )
    assert against_a != against_b


def test_delta_and_full_plans_over_one_cohort_are_distinct() -> None:
    """A delta plan and a full plan over one cohort must not collide."""
    roster = roster_of(("0000001985",))
    full = derive_plan_id_direct(roster.roster_id, 1)
    delta = derive_plan_id_direct(roster.roster_id, 1, kind="delta", parent_id="base")
    assert full != delta


def test_limit_binds_identity_before_the_plan_is_built(tmp_path: Path) -> None:
    """A bounded plan and a full plan over one file must not collide.

    The limit is applied while the cohort is compiled, before identity is derived,
    which is what keeps `--limit 500` and a full run off one plan directory and one
    checkpoint namespace.
    """
    full = build_plan(
        compiled_cohort("cik_sec_mini.csv", tmp_path).roster, chunk_size=2
    )
    bounded = compiled_cohort("cik_sec_mini.csv", tmp_path, limit=2)
    limited = build_plan(
        bounded.roster, chunk_size=2, selected_limit=bounded.selected_limit
    )
    assert limited.plan_id != full.plan_id
    assert limited.row_count == 2
    assert limited.selected_limit == 2
    assert full.selected_limit is None


def test_limit_records_provenance(tmp_path: Path) -> None:
    cohort = compiled_cohort("cik_sec_mini.csv", tmp_path, limit=2)
    plan = build_plan(
        cohort.roster,
        chunk_size=2,
        input_fingerprint=cohort.input_fingerprint,
        selected_limit=cohort.selected_limit,
    )
    assert plan.input_fingerprint == cohort.input_fingerprint
    assert plan.to_manifest()["selected_limit"] == 2


def test_limit_must_be_positive(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="limit"):
        compiled_cohort("cik_sec_mini.csv", tmp_path, limit=0)


def test_invalid_chunk_size_rejected() -> None:
    with pytest.raises(ValueError, match="chunk_size"):
        _plan(chunk_size=0)
    with pytest.raises(ValueError, match="chunk_size"):
        derive_plan_id_direct("roster", 0)


def test_empty_roster_cannot_be_planned() -> None:
    from edgar_sec.pipelines.metadata_sync.roster import empty_roster

    with pytest.raises(RosterError, match="non-empty roster"):
        build_plan(empty_roster())


def test_chunk_outside_the_plan_is_refused() -> None:
    plan = _plan(chunk_size=2)
    with pytest.raises(RosterError, match="not present in plan"):
        plan.chunk_ciks(7)


def test_ordinal_outside_the_roster_is_refused() -> None:
    with pytest.raises(RosterError, match="outside the roster"):
        _plan(chunk_size=2).chunk_id_of(9)


def test_plan_records_the_current_versions() -> None:
    plan = _plan(chunk_size=2)
    assert plan.schema_version == SCHEMA_VERSION
    assert plan.plan_format_version == PLAN_FORMAT_VERSION


def test_bundle_round_trip_preserves_the_plan(tmp_path: Path) -> None:
    plan = _plan(chunk_size=2)
    run_paths = resolve_run_paths(plan.plan_id, tmp_path)
    write_plan(plan, run_paths)
    assert run_paths.plan_file.is_file()
    assert run_paths.roster_file.is_file()
    assert run_paths.input_manifest_file.is_file()
    loaded = load_plan(run_paths)
    assert loaded.plan_id == plan.plan_id
    assert loaded.roster == plan.roster
    assert loaded.chunk_ciks(0) == plan.chunk_ciks(0)


def test_bundle_manifest_records_the_roster_digest(tmp_path: Path) -> None:
    plan = _plan(chunk_size=2)
    run_paths = resolve_run_paths(plan.plan_id, tmp_path)
    digest = write_plan(plan, run_paths)
    manifest = json.loads(run_paths.plan_file.read_text(encoding="utf-8"))
    assert manifest["roster_artifact_sha256"] == digest
    assert manifest["roster_id"] == plan.roster.roster_id


def test_load_rejects_a_tampered_row_count(tmp_path: Path) -> None:
    plan = _plan(chunk_size=2)
    run_paths = resolve_run_paths(plan.plan_id, tmp_path)
    write_plan(plan, run_paths)
    manifest = json.loads(run_paths.plan_file.read_text(encoding="utf-8"))
    manifest["row_count"] = 99
    run_paths.plan_file.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="corrupt plan"):
        load_plan(run_paths)


def test_load_rejects_a_swapped_roster(tmp_path: Path) -> None:
    """A cohort replaced beside a plan must not drive a fetch."""
    plan = _plan(chunk_size=2)
    run_paths = resolve_run_paths(plan.plan_id, tmp_path)
    write_plan(plan, run_paths)
    from edgar_sec.pipelines.metadata_sync.roster import write_roster

    write_roster(roster_of(("0000099999",)), run_paths.roster_file)
    with pytest.raises(ValueError, match="identity"):
        load_plan(run_paths)


def test_load_rejects_a_missing_roster(tmp_path: Path) -> None:
    plan = _plan(chunk_size=2)
    run_paths = resolve_run_paths(plan.plan_id, tmp_path)
    write_plan(plan, run_paths)
    run_paths.roster_file.unlink()
    with pytest.raises(FileNotFoundError):
        load_plan(run_paths)


def test_load_rejects_a_stale_plan_id(tmp_path: Path) -> None:
    plan = _plan(chunk_size=2)
    run_paths = resolve_run_paths(plan.plan_id, tmp_path)
    write_plan(plan, run_paths)
    manifest = json.loads(run_paths.plan_file.read_text(encoding="utf-8"))
    manifest["chunk_size"] = 3
    run_paths.plan_file.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="stale plan"):
        load_plan(run_paths)


def test_load_missing_plan_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_plan(resolve_run_paths("deadbeef", tmp_path))


def test_load_rejects_a_forged_schema_version(tmp_path: Path) -> None:
    plan = _plan(chunk_size=2)
    run_paths = resolve_run_paths(plan.plan_id, tmp_path)
    write_plan(plan, run_paths)
    _retag(run_paths, "schema_version", "0.0.1-FORGED")
    with pytest.raises(ValueError, match="schema_version"):
        load_plan(run_paths)


def test_load_rejects_a_missing_schema_version(tmp_path: Path) -> None:
    plan = _plan(chunk_size=2)
    run_paths = resolve_run_paths(plan.plan_id, tmp_path)
    write_plan(plan, run_paths)
    _retag(run_paths, "schema_version", None)
    with pytest.raises(ValueError, match="schema_version"):
        load_plan(run_paths)


def test_load_rejects_a_foreign_plan_format_version(tmp_path: Path) -> None:
    plan = _plan(chunk_size=2)
    run_paths = resolve_run_paths(plan.plan_id, tmp_path)
    write_plan(plan, run_paths)
    _retag(run_paths, "plan_format_version", "99.0.0")
    with pytest.raises(ValueError, match="plan_format_version"):
        load_plan(run_paths)


def test_load_rejects_a_foreign_manifest_kind(tmp_path: Path) -> None:
    plan = _plan(chunk_size=2)
    run_paths = resolve_run_paths(plan.plan_id, tmp_path)
    write_plan(plan, run_paths)
    _retag(run_paths, "manifest_kind", "something_else")
    with pytest.raises(ValueError, match="manifest_kind"):
        load_plan(run_paths)


def test_options_derive_the_same_plan_id_the_planner_builds(tmp_path: Path) -> None:
    derived = derive_plan_id(
        plan_options(input_path=fixture_path("cik_sec_mini.csv"), chunk_size=2)
    )
    assert derived == _plan(chunk_size=2).plan_id


def test_utc_stamp_is_second_resolution() -> None:
    stamp = utc_now_iso()
    assert stamp.endswith("Z") and len(stamp) == 20


def _retag(run_paths, key: str, value: str | None) -> None:
    manifest = json.loads(run_paths.plan_file.read_text(encoding="utf-8"))
    if value is None:
        manifest.pop(key, None)
    else:
        manifest[key] = value
    run_paths.plan_file.write_text(json.dumps(manifest), encoding="utf-8")
