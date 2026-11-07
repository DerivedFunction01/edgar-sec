"""Ledger status: tip, per-source counts, and latest fetch per source."""

from __future__ import annotations

from edgar_sec.foundation.runtime.render import KeyValueRow, ProseRow, render_output
from edgar_sec.pipelines.feeds.ledger import ledger_stats
from edgar_sec.pipelines.feeds.options import FeedsOptions


def cmd_status(options: FeedsOptions) -> int:
    """Report the published ledger state without fetching anything."""
    stats = ledger_stats(options.feeds_paths(), branch=options.branch)
    if stats is None:
        render_output(
            [
                KeyValueRow("ledger", "absent"),
                ProseRow("no feed-events ledger is published under this root"),
            ],
            title="Feeds Status",
        )
        return 0
    rows = [
        KeyValueRow("tip_snapshot_id", stats.tip_snapshot_id),
        KeyValueRow("total_rows", str(stats.total_rows)),
        KeyValueRow("distinct_accessions", str(stats.distinct_accessions)),
    ]
    for source in stats.per_source:
        latest = source.latest_fetched_at or "never"
        rows.append(
            KeyValueRow(
                f"source_{source.source}",
                f"rows={source.row_count} latest_fetch={latest}",
            )
        )
    render_output(rows, title="Feeds Status")
    return 0


__all__ = ["cmd_status"]
