"""Cohort planning and progress inspection commands."""

from __future__ import annotations

from edgar_sec.foundation.runtime.render import KeyValueRow, render_output
from edgar_sec.pipelines.metadata_sync.checkpoints import (
    discover_completed_chunks,
)
from edgar_sec.pipelines.metadata_sync.options import (
    PlanOptions,
    RunOptions,
    resolve_cohort,
)
from edgar_sec.pipelines.metadata_sync.paths import resolve_run_paths
from edgar_sec.pipelines.metadata_sync.planner import (
    build_plan,
    load_plan,
    write_plan,
)


def cmd_plan(options: PlanOptions) -> int:
    """Generate a deterministic plan without touching the network."""
    cohort = resolve_cohort(options)
    plan = build_plan(
        cohort.roster,
        chunk_size=options.chunk_size,
        input_name=cohort.input_name,
        input_fingerprint=cohort.input_fingerprint,
        selected_limit=options.limit,
    )
    run_paths = resolve_run_paths(plan.plan_id, options.artifacts_root)
    write_plan(plan, run_paths)
    render_output(
        [
            KeyValueRow("plan_id", plan.plan_id),
            KeyValueRow("roster_id", plan.roster.roster_id),
            KeyValueRow("row_count", str(plan.row_count)),
            KeyValueRow("chunk_size", str(plan.chunk_size)),
            KeyValueRow("chunk_count", str(plan.chunk_count)),
        ],
        title="Plan Generated",
    )
    return 0


def cmd_status(options: RunOptions) -> int:
    """Report plan progress without refetching any source data."""
    run_paths = options.run_paths()
    plan = load_plan(run_paths)
    completed = discover_completed_chunks(plan, run_paths)
    planned = plan.chunk_ids()
    outstanding = [chunk_id for chunk_id in planned if chunk_id not in completed]
    render_output(
        [
            KeyValueRow("plan_id", plan.plan_id),
            KeyValueRow("roster_id", plan.roster.roster_id),
            KeyValueRow("row_count", str(plan.row_count)),
            KeyValueRow("planned_chunks", str(len(planned))),
            KeyValueRow("completed_chunks", str(len(completed))),
            KeyValueRow("mergeable", str(not outstanding)),
            KeyValueRow("schema_version", str(plan.schema_version)),
        ],
        title=f"Plan Status ({plan.plan_id[:8]})",
    )
    return 0
