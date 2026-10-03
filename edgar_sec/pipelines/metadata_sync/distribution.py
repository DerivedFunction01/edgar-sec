"""Copy-based distribution of a plan across machines.
The bundle is byte-identical for every worker, so a worker verifies what it holds
instead of trusting it; a receipt is the only thing crossing the machine
boundary, so import can refuse anything it cannot prove matches the plan.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from edgar_sec.foundation.hashing import file_sha256

from .assignment import (
    Assignment,
    AssignmentError,
    ChunkResultRecord,
    build_assignment,
    build_receipt,
    divide_chunks,
    finalize_receipt,
    read_assignment,
    read_receipt,
    write_assignment,
    write_receipt,
)
from .checkpoints import inspect_chunk
from .options import BundleRunPaths, RunOptions
from .paths import resolve_run_paths
from .planner import Plan, load_plan, utc_now_iso

__all__ = [
    "adopt_chunks",
    "build_worker_receipt",
    "coordinator_run_paths",
    "copy_bundle",
    "export_bundle",
    "load_returned_plan",
    "read_returned_assignment",
    "select_assignment",
    "worker_chunk_records",
    "write_receipt",
]


def coordinator_run_paths(options: RunOptions) -> Any:
    """Plan-scoped paths on the coordinator that adopts returned chunks."""
    return resolve_run_paths(options.plan_id, options.artifacts_root)


def export_bundle(
    plan: Plan, run_paths: Any, *, worker_count: int, destination: Path
) -> list[dict[str, Any]]:
    """Write one bundle per worker and return what each one holds.
    A worker with no chunk is skipped: an empty assignment would assert
    responsibility for work that does not exist.
    """
    destination.mkdir(parents=True, exist_ok=True)
    exported: list[dict[str, Any]] = []
    for worker_id, chunk_ids in divide_chunks(plan.chunk_count, worker_count).items():
        if not chunk_ids:
            continue
        assignment = build_assignment(plan.plan_id, worker_id, list(chunk_ids))
        bundle = destination / worker_id
        bundle.mkdir(parents=True, exist_ok=True)
        copy_bundle(run_paths, bundle)
        digest = write_assignment(
            assignment, BundleRunPaths(bundle_root=bundle, plan_id=plan.plan_id)
        )
        exported.append(
            {
                "worker_id": worker_id,
                "assignment_id": assignment.assignment_id,
                "chunk_ids": list(chunk_ids),
                "assignment_sha256": digest,
                "bundle": str(bundle),
            }
        )
    return exported


def copy_bundle(source: Any, bundle: Path) -> None:
    """Copy the plan manifest, roster, and input diagnostics into a bundle."""
    (bundle / "roster").mkdir(parents=True, exist_ok=True)
    shutil.copy2(source.plan_file, bundle / "plan.json")
    shutil.copy2(source.roster_file, bundle / "roster" / "ciks.parquet")
    if source.input_manifest_file.is_file():
        (bundle / "input").mkdir(parents=True, exist_ok=True)
        shutil.copy2(
            source.input_manifest_file, bundle / "input" / "input_manifest.json"
        )


def select_assignment(options: RunOptions, run_paths: Any) -> Assignment:
    """Find the one assignment this worker was handed.
    Several in one bundle requires naming the worker.
    """
    candidates = sorted(run_paths.assignments_dir.glob("*.parquet"))
    if not candidates:
        raise AssignmentError(
            f"bundle carries no assignment: {run_paths.assignments_dir}"
        )
    if options.worker_id:
        for candidate in candidates:
            assignment = read_assignment(candidate)
            if assignment.worker_id == options.worker_id:
                return assignment
        raise AssignmentError(
            f"no assignment for worker {options.worker_id!r} in "
            f"{run_paths.assignments_dir}"
        )
    if len(candidates) > 1:
        raise AssignmentError(
            f"bundle carries {len(candidates)} assignments; name one with --worker"
        )
    return read_assignment(candidates[0])


def worker_chunk_records(
    results: list[Any], bundle_root: Path
) -> list[ChunkResultRecord]:
    """Describe each produced chunk file the way the coordinator will read it.
    Already-complete chunks are omitted: a worker that contributed nothing must not
    claim it did.
    """
    return [
        ChunkResultRecord(
            chunk_id=result.chunk_id,
            relative_path=Path(result.path).relative_to(bundle_root).as_posix(),
            row_count=result.row_count,
            file_sha256=file_sha256(result.path),
        )
        for result in results
        if not result.skipped_existing
    ]


def build_worker_receipt(
    plan: Plan, assignment: Assignment, results: list[Any], bundle_root: Path
) -> Any:
    """Build and sign the receipt a worker hands back with its chunk files."""
    return finalize_receipt(
        build_receipt(
            plan_id=plan.plan_id,
            assignment=assignment,
            chunks=worker_chunk_records(results, bundle_root),
        ),
        utc_now_iso(),
    )


def read_returned_assignment(source: Path, receipt: Any) -> Assignment:
    """Load the assignment the returned bundle was produced under."""
    path = source / "assignments" / f"{receipt.assignment_id}.parquet"
    if not path.is_file():
        raise AssignmentError(f"returned assignment not found: {path}")
    assignment = read_assignment(path)
    if assignment.assignment_id != receipt.assignment_id:
        raise AssignmentError(
            f"receipt names assignment {receipt.assignment_id!r}, the bundle "
            f"carries {assignment.assignment_id!r}"
        )
    return assignment


def load_returned_plan(run_paths: Any, source: Path) -> tuple[Plan, Any, Assignment]:
    """Load the plan and validate a returned bundle's receipt against it."""
    plan = load_plan(run_paths)
    receipt = read_receipt(source / "receipt.json")
    if receipt.plan_id != plan.plan_id:
        raise AssignmentError(
            f"receipt is for plan {receipt.plan_id!r}, this is plan {plan.plan_id!r}"
        )
    return plan, receipt, read_returned_assignment(source, receipt)


def adopt_chunks(
    plan: Plan,
    run_paths: Any,
    source: Path,
    receipt: Any,
    assignment: Assignment,
) -> tuple[list[int], list[int]]:
    """Verify a returned bundle and place its chunk files for the merge.
    Everything is checked before a byte is placed. A byte-identical re-import is a
    no-op; a *conflicting* one is an error, never an overwrite.
    """
    assigned = set(assignment.chunk_ids)
    adopted: list[int] = []
    ignored: list[int] = []
    for record in receipt.chunks:
        if record.chunk_id not in assigned:
            raise AssignmentError(
                f"receipt claims chunk {record.chunk_id}, which its assignment "
                "does not name"
            )
        if record.chunk_id not in plan.chunk_ids():
            raise AssignmentError(
                f"receipt claims chunk {record.chunk_id}, which plan "
                f"{plan.plan_id} does not plan"
            )
        incoming = source / record.relative_path
        if not incoming.is_file():
            raise AssignmentError(f"receipt names a missing file: {incoming}")
        if file_sha256(incoming) != record.file_sha256:
            raise AssignmentError(
                f"chunk {record.chunk_id} digest does not match its receipt: {incoming}"
            )
        if (
            inspect_chunk(
                record.chunk_id,
                incoming,
                expected_ciks=plan.chunk_ciks(record.chunk_id),
                expected_fingerprint=plan.input_fingerprint or None,
            )
            is None
        ):
            raise AssignmentError(
                f"chunk {record.chunk_id} failed validation: schema, row count, or "
                f"CIK coverage differs from plan {plan.plan_id}"
            )
        target = run_paths.chunk_file(record.chunk_id)
        if target.is_file():
            existing = inspect_chunk(
                record.chunk_id,
                target,
                expected_ciks=plan.chunk_ciks(record.chunk_id),
                expected_fingerprint=plan.input_fingerprint or None,
            )
            if existing is not None and existing.file_sha256 == record.file_sha256:
                ignored.append(record.chunk_id)
                continue
            raise AssignmentError(
                f"chunk {record.chunk_id} is already present with different "
                "content; resolve the conflict before importing"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(incoming, target)
        adopted.append(record.chunk_id)
    return sorted(adopted), sorted(ignored)
