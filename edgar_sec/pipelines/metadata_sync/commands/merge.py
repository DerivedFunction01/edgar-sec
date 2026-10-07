"""Chunk merge and snapshot publication command."""

from __future__ import annotations

from edgar_sec.foundation.runtime.render import KeyValueRow, render_output
from edgar_sec.pipelines.metadata_sync.merger import (
    merge_chunks,
    publish_snapshot,
)
from edgar_sec.pipelines.metadata_sync.options import RunOptions
from edgar_sec.pipelines.metadata_sync.planner import load_plan
from edgar_sec.pipelines.metadata_sync.progress import (
    MERGE_PROGRESS_STAGES,
    progress_renderer,
)
from edgar_sec.pipelines.metadata_sync.run_lock import RunLock


def cmd_merge(options: RunOptions, *, lineage: dict[str, str] | None = None) -> int:
    """Validate every chunk and publish a snapshot."""
    run_paths = options.run_paths()
    plan = load_plan(run_paths)
    progress, bar = progress_renderer(
        "merge", MERGE_PROGRESS_STAGES, desc=f"merge {plan.plan_id[:8]}"
    )
    try:
        with RunLock(run_paths.lock_path(), stale_lock_confirmed=False):
            report = merge_chunks(
                plan,
                run_paths,
                options.effective_snapshot_id(plan),
                lineage=lineage,
                progress=progress,
            )
    finally:
        if bar is not None:
            bar.close()
    manifest = publish_snapshot(report, run_paths.metadata)
    render_output(
        [
            KeyValueRow("snapshot_id", manifest["snapshot_id"]),
            KeyValueRow("row_count", str(manifest["row_count"])),
            KeyValueRow(
                "part_count",
                str(manifest.get("part_count", len(report.parts))),
            ),
            KeyValueRow("parts_digest", manifest.get("parts_digest", "")[:16]),
            KeyValueRow(
                "duplicate_count",
                str(manifest.get("duplicate_count", 0)),
            ),
        ],
        title=f"Snapshot Published ({manifest['snapshot_id'][:8]})",
    )
    return 0
