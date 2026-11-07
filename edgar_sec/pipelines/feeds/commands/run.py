"""Live structured-disclosure run: fetch the four feeds, publish the ledger."""

from __future__ import annotations

from datetime import UTC, datetime

from edgar_sec.engine.feeds.client import FeedClient, dedupe_events
from edgar_sec.foundation.runtime.render import KeyValueRow, render_output
from edgar_sec.pipelines.feeds.ledger import publish_events
from edgar_sec.pipelines.feeds.options import FeedsOptions

from .client import build_feed_client


def cmd_run(
    options: FeedsOptions,
    *,
    feed_client: FeedClient | None = None,
    now: datetime | None = None,
) -> int:
    """Fetch every selected live feed and publish its new events."""
    client = feed_client or build_feed_client()
    fetched_at = now or datetime.now(UTC)
    raw_counts: dict[str, int] = {}
    events = []
    for feed in options.feeds:
        failures_before = len(client.parse_failures)
        feed_events = client.live_feed_events(feed)
        raw_counts[feed] = len(feed_events) + (
            len(client.parse_failures) - failures_before
        )
        events.extend(feed_events)
    deduped = dedupe_events(events)
    result = publish_events(
        options.feeds_paths(),
        deduped,
        command="run",
        fetched_at=fetched_at,
        branch=options.branch,
    )
    rows = [
        KeyValueRow("command", "run"),
        KeyValueRow("tip_before", result.tip_before or "none"),
        KeyValueRow("published", str(result.published)),
        KeyValueRow("snapshot_id", result.snapshot_id or "none"),
        KeyValueRow("deduped_events", str(len(deduped))),
        KeyValueRow("new_rows", str(result.new_rows)),
        KeyValueRow("total_rows", str(result.total_rows)),
    ]
    rows.extend(
        KeyValueRow(f"raw_entries_{feed}", str(raw_counts[feed]))
        for feed in options.feeds
    )
    rows.extend(
        KeyValueRow(f"new_rows_{source}", str(count))
        for source, count in sorted(result.per_source_new.items())
    )
    render_output(rows, title="Feeds Run")
    return 0


__all__ = ["cmd_run"]
