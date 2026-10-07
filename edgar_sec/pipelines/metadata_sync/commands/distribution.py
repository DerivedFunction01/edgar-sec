"""Distributed bundle export, worker run, and chunk import commands."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.foundation.runtime.render import (
    Grid,
    KeyValueRow,
    render_output,
)
from edgar_sec.pipelines.metadata_sync.assignment import AssignmentError
from edgar_sec.pipelines.metadata_sync.distribution import (
    adopt_chunks,
    build_worker_receipt,
    coordinator_run_paths,
    export_bundle,
    load_returned_plan,
    select_assignment,
    write_receipt,
)
from edgar_sec.pipelines.metadata_sync.options import RunOptions
from edgar_sec.pipelines.metadata_sync.planner import load_plan
from edgar_sec.pipelines.metadata_sync.sec_client import SubmissionsClient
from edgar_sec.pipelines.metadata_sync.worker import (
    resolve_workers,
    run_chunk_ids,
)

from .client import build_client


def cmd_export(options: RunOptions, *, worker_count: int, destination: Path) -> int:
    """Copy the immutable plan bundle out, one directory per worker."""
    plan = load_plan(coordinator_run_paths(options))
    workers = export_bundle(
        plan,
        coordinator_run_paths(options),
        worker_count=worker_count,
        destination=destination,
    )
    rows = tuple(
        (
            w["worker_id"],
            w["assignment_id"][:16],
            str(len(w.get("chunk_ids", ()))),
        )
        for w in workers
    )
    render_output(
        [
            KeyValueRow("plan_id", plan.plan_id),
            KeyValueRow("roster_id", plan.roster.roster_id),
            KeyValueRow("row_count", str(plan.row_count)),
            KeyValueRow("chunk_count", str(plan.chunk_count)),
            KeyValueRow("destination", str(destination)),
            Grid(headers=("Worker", "Assignment", "Chunks"), rows=rows),
        ],
        title="Plan Bundles Exported",
    )
    return 0


def cmd_worker(options: RunOptions, *, client: SubmissionsClient | None = None) -> int:
    """Run assigned chunks from a worker bundle and emit a receipt."""
    run_paths = options.run_paths()
    plan = load_plan(run_paths)
    assignment = select_assignment(options, run_paths)
    if assignment.plan_id != plan.plan_id:
        raise AssignmentError(
            f"assignment belongs to plan {assignment.plan_id!r}, "
            f"this bundle is plan {plan.plan_id!r}"
        )
    results = run_chunk_ids(
        client or build_client(),
        plan,
        run_paths,
        list(assignment.chunk_ids),
        snapshot_id=options.effective_snapshot_id(plan),
        workers=resolve_workers(options.workers),
    )
    receipt = build_worker_receipt(plan, assignment, results, run_paths.bundle_root)
    write_receipt(receipt, run_paths.receipt_file)
    render_output(
        [
            KeyValueRow("plan_id", receipt.plan_id),
            KeyValueRow("worker_id", receipt.worker_id),
            KeyValueRow("assignment_id", receipt.assignment_id),
            KeyValueRow("chunk_count", str(len(receipt.chunk_ids()))),
            KeyValueRow("row_count", str(receipt.row_count)),
        ],
        title=f"Worker Completed ({receipt.worker_id})",
    )
    return 0


def cmd_import(options: RunOptions, *, source: Path) -> int:
    """Verify and adopt a worker bundle's returned chunks."""
    run_paths = coordinator_run_paths(options)
    plan, receipt, assignment = load_returned_plan(run_paths, source)
    adopted, ignored = adopt_chunks(plan, run_paths, source, receipt, assignment)
    render_output(
        [
            KeyValueRow("plan_id", plan.plan_id),
            KeyValueRow("worker_id", receipt.worker_id),
            KeyValueRow("assignment_id", assignment.assignment_id),
            KeyValueRow("imported_chunks", str(len(adopted))),
            KeyValueRow("already_present", str(len(ignored))),
        ],
        title="Worker Chunks Imported",
    )
    return 0
