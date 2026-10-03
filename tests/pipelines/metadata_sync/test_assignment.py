"""Static assignment and worker-receipt tests.

Assignment is the artifact that makes multi-machine work a copy operation rather
than a scheduling conversation, so the properties that matter are that its
identity is re-derivable from its own contents, that it never reaches a plan
identity, and that a receipt can be refused when it does not describe what it
claims to.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edgar_sec.pipelines.metadata_sync.assignment import (
    ASSIGNMENT_SCHEMA_VERSION,
    RECEIPT_SCHEMA_VERSION,
    AssignmentError,
    ChunkResultRecord,
    build_assignment,
    build_receipt,
    derive_assignment_id,
    divide_chunks,
    finalize_receipt,
    read_assignment,
    read_receipt,
    write_assignment,
    write_receipt,
)
from edgar_sec.pipelines.metadata_sync.paths import resolve_run_paths
from edgar_sec.pipelines.metadata_sync.planner import build_plan, write_plan
from edgar_sec.pipelines.metadata_sync.roster import roster_from_manifest
from tests.support import fixture_path

PLAN_ID = "0123456789abcdef"


def _run_paths(tmp_path: Path, plan_id: str = PLAN_ID):
    return resolve_run_paths(plan_id, tmp_path)


def test_division_is_deterministic_and_disjoint() -> None:
    first = divide_chunks(7, 3)
    assert first == divide_chunks(7, 3)
    assert sorted(chunk for ids in first.values() for chunk in ids) == list(range(7))
    assert first == {"worker-00": [0, 3, 6], "worker-01": [1, 4], "worker-02": [2, 5]}


def test_division_rejects_nonsense_counts() -> None:
    with pytest.raises(ValueError, match="worker_count"):
        divide_chunks(4, 0)
    with pytest.raises(ValueError, match="chunk_count"):
        divide_chunks(0, 2)


def test_assignment_identity_follows_plan_worker_and_chunks() -> None:
    assert derive_assignment_id(PLAN_ID, "w", [0, 1]) == derive_assignment_id(
        PLAN_ID, "w", [1, 0]
    )
    assert derive_assignment_id(PLAN_ID, "w", [0, 1]) != derive_assignment_id(
        "ffffffffffffffff", "w", [0, 1]
    )
    assert derive_assignment_id(PLAN_ID, "w", [0, 1]) != derive_assignment_id(
        PLAN_ID, "x", [0, 1]
    )
    assert derive_assignment_id(PLAN_ID, "w", [0, 1]) != derive_assignment_id(
        PLAN_ID, "w", [0, 2]
    )


def test_assignment_identity_is_not_a_plan_identity() -> None:
    """Two assignments of one plan differ while the plan does not."""
    from edgar_sec.pipelines.metadata_sync.manifest import read_cik_manifest
    from edgar_sec.pipelines.metadata_sync.planner import derive_plan_id

    plan = build_plan(
        roster_from_manifest(read_cik_manifest(fixture_path("cik_sec_mini.csv"))),
        chunk_size=2,
    )
    left = build_assignment(plan.plan_id, "worker-00", [0])
    right = build_assignment(plan.plan_id, "worker-01", [1])
    assert left.assignment_id != right.assignment_id
    assert plan.plan_id == derive_plan_id(plan.roster.roster_id, plan.chunk_size)


def test_empty_assignment_is_refused() -> None:
    with pytest.raises(AssignmentError, match="no chunks"):
        build_assignment(PLAN_ID, "worker-00", [])


def test_assignment_round_trip(tmp_path: Path) -> None:
    assignment = build_assignment(PLAN_ID, "worker-00", [2, 0, 1])
    digest = write_assignment(assignment, _run_paths(tmp_path))
    assert len(digest) == 64
    loaded = read_assignment(
        _run_paths(tmp_path).assignment_file(assignment.assignment_id)
    )
    assert loaded == assignment


def test_assignment_is_stored_beside_the_plan_not_inside_it(tmp_path: Path) -> None:
    assignment = build_assignment(PLAN_ID, "worker-00", [0])
    run_paths = _run_paths(tmp_path)
    write_assignment(assignment, run_paths)
    assert run_paths.assignment_file(assignment.assignment_id).parent == (
        run_paths.plan_bundle / "assignments"
    )


def test_read_rejects_a_forged_identity(tmp_path: Path) -> None:
    assignment = build_assignment(PLAN_ID, "worker-00", [0, 1])
    path = _run_paths(tmp_path).assignment_file(assignment.assignment_id)
    write_assignment(assignment, _run_paths(tmp_path))

    import pyarrow as pa

    from edgar_sec.infra.storage.parquet import write_parquet_table
    from edgar_sec.pipelines.metadata_sync.assignment import ASSIGNMENT_SCHEMA

    write_parquet_table(
        pa.Table.from_pylist(
            [
                {
                    "assignment_id": "forged",
                    "plan_id": PLAN_ID,
                    "worker_id": "worker-00",
                    "chunk_id": 0,
                }
            ],
            schema=ASSIGNMENT_SCHEMA,
        ),
        path,
    )
    with pytest.raises(AssignmentError, match="contents derive"):
        read_assignment(path)


def test_read_rejects_a_mixed_assignment(tmp_path: Path) -> None:
    import pyarrow as pa

    from edgar_sec.infra.storage.parquet import write_parquet_table
    from edgar_sec.pipelines.metadata_sync.assignment import ASSIGNMENT_SCHEMA

    path = _run_paths(tmp_path).assignment_file("mixed")
    write_parquet_table(
        pa.Table.from_pylist(
            [
                {
                    "assignment_id": derive_assignment_id(PLAN_ID, "w", [0]),
                    "plan_id": PLAN_ID,
                    "worker_id": "a",
                    "chunk_id": 0,
                },
                {
                    "assignment_id": derive_assignment_id(PLAN_ID, "w", [1]),
                    "plan_id": PLAN_ID,
                    "worker_id": "b",
                    "chunk_id": 1,
                },
            ],
            schema=ASSIGNMENT_SCHEMA,
        ),
        path,
    )
    with pytest.raises(AssignmentError, match="mixes"):
        read_assignment(path)


def test_read_missing_assignment_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_assignment(_run_paths(tmp_path).assignment_file("absent"))


def test_receipt_round_trip(tmp_path: Path) -> None:
    assignment = build_assignment(PLAN_ID, "worker-00", [0, 1])
    receipt = finalize_receipt(
        build_receipt(
            plan_id=PLAN_ID,
            assignment=assignment,
            chunks=[
                ChunkResultRecord(0, "chunks/chunk_0000.parquet", 1000, "a" * 64),
                ChunkResultRecord(1, "chunks/chunk_0001.parquet", 1000, "b" * 64),
            ],
        ),
        "2026-01-01T00:00:00Z",
    )
    path = write_receipt(receipt, tmp_path / "receipt.json")
    assert path.name == "receipt.json"
    loaded = read_receipt(path)
    assert loaded.chunk_ids() == [0, 1]
    assert loaded.worker_id == "worker-00"
    assert loaded.row_count == 2000


def test_receipt_orders_chunks_regardless_of_arrival(tmp_path: Path) -> None:
    assignment = build_assignment(PLAN_ID, "worker-00", [0, 1])
    receipt = finalize_receipt(
        build_receipt(
            plan_id=PLAN_ID,
            assignment=assignment,
            chunks=[
                ChunkResultRecord(1, "chunks/chunk_0001.parquet", 5, "b" * 64),
                ChunkResultRecord(0, "chunks/chunk_0000.parquet", 5, "a" * 64),
            ],
        ),
        "2026-01-01T00:00:00Z",
    )
    assert receipt.chunk_ids() == [0, 1]


def test_receipt_detects_an_edited_chunk_list(tmp_path: Path) -> None:
    """A receipt is the only thing crossing a machine boundary, so it is checked."""
    assignment = build_assignment(PLAN_ID, "worker-00", [0, 1])
    receipt = finalize_receipt(
        build_receipt(
            plan_id=PLAN_ID,
            assignment=assignment,
            chunks=[ChunkResultRecord(0, "chunks/chunk_0000.parquet", 5, "a" * 64)],
        ),
        "2026-01-01T00:00:00Z",
    )
    path = write_receipt(receipt, tmp_path / "receipt.json")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["chunks"].append(
        {
            "chunk_id": 1,
            "relative_path": "chunks/chunk_0001.parquet",
            "row_count": 5,
            "file_sha256": "c" * 64,
        }
    )
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(AssignmentError, match="contents derive"):
        read_receipt(path)


def test_receipt_detects_a_swapped_plan(tmp_path: Path) -> None:
    assignment = build_assignment(PLAN_ID, "worker-00", [0])
    receipt = finalize_receipt(
        build_receipt(
            plan_id=PLAN_ID,
            assignment=assignment,
            chunks=[ChunkResultRecord(0, "chunks/chunk_0000.parquet", 5, "a" * 64)],
        ),
        "2026-01-01T00:00:00Z",
    )
    path = write_receipt(receipt, tmp_path / "receipt.json")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["plan_id"] = "ffffffffffffffff"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(AssignmentError, match="contents derive"):
        read_receipt(path)


def test_receipt_rejects_a_foreign_version(tmp_path: Path) -> None:
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps({"receipt_schema_version": "99.0.0"}), encoding="utf-8")
    with pytest.raises(AssignmentError, match="version"):
        read_receipt(path)


def test_receipt_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_receipt(tmp_path / "receipt.json")


def test_versions_are_declared_once() -> None:
    assert ASSIGNMENT_SCHEMA_VERSION == "1.0.0"
    assert RECEIPT_SCHEMA_VERSION == "1.0.0"


def test_reassignment_does_not_disturb_a_written_plan(tmp_path: Path) -> None:
    """Work survives reassignment."""
    from edgar_sec.pipelines.metadata_sync.manifest import read_cik_manifest

    plan = build_plan(
        roster_from_manifest(read_cik_manifest(fixture_path("cik_sec_mini.csv"))),
        chunk_size=2,
    )
    run_paths = _run_paths(tmp_path, plan.plan_id)
    write_plan(plan, run_paths)
    (run_paths.chunk_dir).mkdir(parents=True, exist_ok=True)
    (run_paths.chunk_dir / "chunk_0000.parquet").write_bytes(b"checkpoint")

    for count in (1, 2, 5):
        for worker_id, chunk_ids in divide_chunks(plan.chunk_count, count).items():
            if not chunk_ids:
                continue
            write_assignment(
                build_assignment(plan.plan_id, worker_id, chunk_ids), run_paths
            )

    from edgar_sec.pipelines.metadata_sync.planner import load_plan

    assert load_plan(run_paths).plan_id == plan.plan_id
    assert (run_paths.chunk_dir / "chunk_0000.parquet").read_bytes() == b"checkpoint"
