"""Deterministic planning, persistence, and staleness tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.pipelines.metadata_sync.manifest import read_cik_manifest
from edgar_sec.pipelines.metadata_sync.paths import resolve_run_paths
from edgar_sec.pipelines.metadata_sync.planner import (
    build_plan,
    derive_plan_id,
    load_plan,
    plan_chunk_ids,
    write_plan,
)
from tests.support import fixture_path


def _plan(**kwargs):
    manifest = read_cik_manifest(fixture_path("cik_sec_mini.csv"))
    return build_plan(manifest, **kwargs)


def test_plan_partitions_ciks_into_chunks() -> None:
    plan = _plan(chunk_size=2, partition_count=1)
    assert plan["row_count"] == 4
    assert [chunk["cik_padded"] for chunk in plan["chunks"]] == [
        ["0000001985", "0000001761"],
        ["0000000020", "0000037996"],
    ]
    assert [chunk["offset"] for chunk in plan["chunks"]] == [0, 2]
    assert plan["partitions"][0]["chunk_ids"] == [0, 1]
    assert plan["partitions"][0]["cik_padded"] == plan["cik_padded"]


def test_plan_is_deterministic_across_runs() -> None:
    first = _plan(chunk_size=2)
    second = _plan(chunk_size=2)
    first.pop("created_at")
    second.pop("created_at")
    assert first == second
    assert first["plan_id"] == second["plan_id"]


def test_plan_id_changes_with_chunking() -> None:
    assert _plan(chunk_size=2)["plan_id"] != _plan(chunk_size=3)["plan_id"]
    assert (
        _plan(chunk_size=2, partition_count=1)["plan_id"]
        != _plan(chunk_size=2, partition_count=2)["plan_id"]
    )


def test_partitions_receive_distinct_chunks() -> None:
    plan = _plan(chunk_size=1, partition_count=2)
    assert len(plan["partitions"]) == 2
    assert plan["partitions"][0]["chunk_ids"] == [0, 2]
    assert plan["partitions"][1]["chunk_ids"] == [1, 3]

    # Round-robin assigns chunks, not CIKs, so union order is a permutation.
    combined = [
        cik for partition in plan["partitions"] for cik in partition["cik_padded"]
    ]
    assert sorted(combined) == sorted(plan["cik_padded"])
    assigned = [cid for part in plan["partitions"] for cid in part["chunk_ids"]]
    assert sorted(assigned) == [0, 1, 2, 3]


def test_plan_id_is_content_derived_not_timestamped() -> None:
    manifest = read_cik_manifest(fixture_path("cik_sec_mini.csv"))
    expected = derive_plan_id(manifest.input_fingerprint, 2, 1)
    assert build_plan(manifest, chunk_size=2, partition_count=1)["plan_id"] == expected
    assert len(expected) == 16


def test_invalid_chunk_size_rejected() -> None:
    with pytest.raises(ValueError, match="chunk_size"):
        _plan(chunk_size=0)
    with pytest.raises(ValueError, match="partition_count"):
        _plan(partition_count=0)


def test_write_and_load_round_trip(tmp_path: Path) -> None:
    plan = _plan(chunk_size=2)
    run_paths = resolve_run_paths(plan["plan_id"], tmp_path)
    write_plan(plan, run_paths)
    assert run_paths.plan_file.is_file()
    assert load_plan(run_paths)["plan_id"] == plan["plan_id"]


def test_load_rejects_tampered_plan(tmp_path: Path) -> None:
    plan = _plan(chunk_size=2)
    run_paths = resolve_run_paths(plan["plan_id"], tmp_path)
    write_plan(plan, run_paths)
    plan["row_count"] = 99
    write_plan(plan, run_paths)
    with pytest.raises(ValueError, match="corrupt plan"):
        load_plan(run_paths)


def test_load_rejects_stale_plan_id(tmp_path: Path) -> None:
    plan = _plan(chunk_size=2)
    run_paths = resolve_run_paths(plan["plan_id"], tmp_path)
    plan["chunk_size"] = 3
    write_plan(plan, run_paths)
    with pytest.raises(ValueError, match="stale plan"):
        load_plan(run_paths)


def test_load_missing_plan_raises(tmp_path: Path) -> None:
    run_paths = resolve_run_paths("deadbeef", tmp_path)
    with pytest.raises(FileNotFoundError):
        load_plan(run_paths)


def test_plan_chunk_ids_filters_by_partition() -> None:
    plan = _plan(chunk_size=1, partition_count=2)
    assert plan_chunk_ids(plan) == [0, 1, 2, 3]
    assert plan_chunk_ids(plan, 1) == [1, 3]
    assert plan_chunk_ids(plan, 99) == []
