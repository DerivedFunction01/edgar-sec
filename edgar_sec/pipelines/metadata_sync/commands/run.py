"""Plan chunk execution command."""

from __future__ import annotations

from edgar_sec.foundation.runtime.render import KeyValueRow, render_output
from edgar_sec.pipelines.metadata_sync.checkpoints import (
    discover_completed_chunks,
)
from edgar_sec.pipelines.metadata_sync.options import RunOptions
from edgar_sec.pipelines.metadata_sync.planner import load_plan
from edgar_sec.pipelines.metadata_sync.progress import progress_renderer
from edgar_sec.pipelines.metadata_sync.run_lock import RunLock
from edgar_sec.pipelines.metadata_sync.sec_client import SubmissionsClient
from edgar_sec.pipelines.metadata_sync.worker import (
    resolve_workers,
    run_chunk_ids,
)

from .client import build_client


def cmd_run(options: RunOptions, *, client: SubmissionsClient | None = None) -> int:
    """Execute the chunks this invocation owns."""
    run_paths = options.run_paths()
    plan = load_plan(run_paths)
    targets = list(options.chunk_ids) or plan.chunk_ids()
    if not targets:
        raise ValueError("no chunks selected")
    completed = discover_completed_chunks(plan, run_paths)
    outstanding = sum(
        plan.chunk_length(chunk_id) for chunk_id in targets if chunk_id not in completed
    )
    progress, bar = progress_renderer(
        "fetch", outstanding, desc=f"plan {plan.plan_id[:8]}"
    )
    try:
        with RunLock(run_paths.lock_path(), stale_lock_confirmed=False):
            results = run_chunk_ids(
                client or build_client(),
                plan,
                run_paths,
                targets,
                snapshot_id=options.effective_snapshot_id(plan),
                workers=resolve_workers(options.workers),
                completed=completed,
                progress=progress,
            )
    finally:
        if bar is not None:
            bar.close()
    written = sum(1 for r in results if not r.skipped_existing)
    render_output(
        [
            KeyValueRow("plan_id", plan.plan_id),
            KeyValueRow("total_chunks", str(len(results))),
            KeyValueRow("written", str(written)),
            KeyValueRow("skipped", str(len(results) - written)),
            KeyValueRow(
                "total_rows",
                str(sum(r.row_count for r in results if not r.skipped_existing)),
            ),
        ],
        title=f"Run Summary ({plan.plan_id[:8]})",
    )
    return 0
