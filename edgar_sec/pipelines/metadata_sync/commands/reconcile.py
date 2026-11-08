"""Daily-index reconciliation command."""

from __future__ import annotations

from edgar_sec.foundation.runtime.render import (
    KeyValueRow,
    ProseRow,
    render_output,
)
from edgar_sec.pipelines.metadata_sync.options import ReconcileOptions
from edgar_sec.pipelines.metadata_sync.paths import resolve_metadata_paths
from edgar_sec.pipelines.metadata_sync.progress import emit_progress_event
from edgar_sec.pipelines.metadata_sync.reconcile import reconcile
from edgar_sec.pipelines.metadata_sync.refresh import branch_tip
from edgar_sec.pipelines.metadata_sync.run_lock import RunLock
from edgar_sec.pipelines.metadata_sync.sec_client import SubmissionsClient

from .client import build_client


def cmd_reconcile(
    options: ReconcileOptions,
    *,
    client: SubmissionsClient | None = None,
    fetch_bytes=None,
) -> int:
    """Reconcile the branch tip against the daily index over a date range."""
    if options.start_date is None or options.end_date is None:
        raise ValueError("--start-date and --end-date are required")
    metadata = resolve_metadata_paths(options.artifacts_root)
    base_id = branch_tip(metadata, options.branch_name)
    http_client = client or build_client()
    with RunLock(
        metadata.snapshot_lock_path(base_id),
        stale_lock_confirmed=options.stale_lock_confirmed,
    ):
        result = reconcile(
            http_client,
            metadata,
            start_date=options.start_date,
            end_date=options.end_date,
            fetch_bytes=fetch_bytes,
            new_snapshot_id=options.new_snapshot_id,
            chunk_size=options.chunk_size,
            workers=options.workers,
            progress=lambda event: emit_progress_event(event, label="reconcile"),
            branch_name=options.branch_name,
            expected_branch_tip=options.expected_branch_tip,
        )
    rows = [
        KeyValueRow("no_op", str(result.no_op)),
        KeyValueRow("base_snapshot_id", result.base_snapshot_id),
        KeyValueRow("start_date", options.start_date.isoformat()),
        KeyValueRow("end_date", options.end_date.isoformat()),
        KeyValueRow("days_pulled", str(result.days_pulled)),
        KeyValueRow("days_missing", str(result.days_missing)),
        KeyValueRow("index_rows", str(result.index_rows)),
        KeyValueRow("malformed_rows", str(result.malformed_rows)),
        KeyValueRow("missing_accessions", str(len(result.missing_accessions))),
        KeyValueRow("affected_ciks", ",".join(result.affected_ciks)),
        KeyValueRow("carried_rows", str(result.carried_rows)),
        KeyValueRow("normalized_rows", str(result.normalized_rows)),
        KeyValueRow("total_row_count", str(result.total_row_count)),
    ]
    if result.no_op:
        rows.append(
            ProseRow(
                "the index proves no accession the tip lacks over this range; "
                "nothing fetched per-CIK and nothing published"
            )
        )
        render_output(rows, title="Reconcile (No-op)")
        return 0
    rows.insert(2, KeyValueRow("new_snapshot_id", result.new_snapshot_id))
    render_output(rows, title="Reconcile Completed")
    return 0
