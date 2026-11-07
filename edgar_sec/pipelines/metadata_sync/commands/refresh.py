"""Current-filings feed refresh command."""

from __future__ import annotations

from edgar_sec.engine.feeds.client import FeedClient
from edgar_sec.foundation.runtime.render import (
    KeyValueRow,
    ProseRow,
    render_output,
)
from edgar_sec.pipelines.metadata_sync.options import RefreshOptions
from edgar_sec.pipelines.metadata_sync.paths import resolve_metadata_paths
from edgar_sec.pipelines.metadata_sync.progress import emit_progress_event
from edgar_sec.pipelines.metadata_sync.refresh import branch_tip, refresh
from edgar_sec.pipelines.metadata_sync.run_lock import RunLock
from edgar_sec.pipelines.metadata_sync.sec_client import SubmissionsClient

from .client import build_client


def cmd_refresh(
    options: RefreshOptions,
    *,
    client: SubmissionsClient | None = None,
    feed_client: FeedClient | None = None,
) -> int:
    """Refresh the branch tip's stale CIKs from the current-filings feed."""
    metadata = resolve_metadata_paths(options.artifacts_root)
    base_id = branch_tip(metadata, options.branch_name)
    http_client = client or build_client()
    feed = feed_client or FeedClient(http_client.http)
    with RunLock(
        metadata.snapshot_lock_path(base_id),
        stale_lock_confirmed=options.stale_lock_confirmed,
    ):
        result = refresh(
            http_client,
            feed,
            metadata,
            base_snapshot_id=base_id,
            new_snapshot_id=options.new_snapshot_id,
            chunk_size=options.chunk_size,
            workers=options.workers,
            progress=lambda event: emit_progress_event(event, label="refresh"),
            branch_name=options.branch_name,
            expected_branch_tip=options.expected_branch_tip,
        )
    rows = [
        KeyValueRow("no_op", str(result.no_op)),
        KeyValueRow("base_snapshot_id", result.base_snapshot_id),
        KeyValueRow("events_seen", str(result.events_seen)),
        KeyValueRow("pages_pulled", str(result.pages_pulled)),
        KeyValueRow("parse_failures", str(result.parse_failures)),
        KeyValueRow("new_accessions", str(len(result.new_accessions))),
        KeyValueRow("affected_ciks", ",".join(result.affected_ciks)),
        KeyValueRow("carried_rows", str(result.carried_rows)),
        KeyValueRow("normalized_rows", str(result.normalized_rows)),
        KeyValueRow("total_row_count", str(result.total_row_count)),
    ]
    if result.no_op:
        rows.append(
            ProseRow(
                "the feed window already matches the tip; "
                "nothing fetched and nothing published"
            )
        )
        render_output(rows, title="Refresh (No-op)")
        return 0
    rows.insert(2, KeyValueRow("new_snapshot_id", result.new_snapshot_id))
    render_output(rows, title="Refresh Completed")
    return 0
