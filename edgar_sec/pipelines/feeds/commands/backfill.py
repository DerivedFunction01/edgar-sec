"""Archive backfill: publish monthly-archive events month by month."""

from __future__ import annotations

from datetime import UTC, date, datetime

from edgar_sec.domain.feeds.models import SOURCE_MONTHLY_ARCHIVE
from edgar_sec.domain.sec_urls import structured_archive_url
from edgar_sec.engine.feeds.client import FeedClient
from edgar_sec.foundation.runtime.render import KeyValueRow, render_output
from edgar_sec.infra.sec_http.client import SecHttpClient
from edgar_sec.pipelines.feeds.ledger import publish_events
from edgar_sec.pipelines.feeds.options import FeedsOptions, format_month, iter_months

from .client import build_feed_client, build_http_client


def cmd_backfill(
    options: FeedsOptions,
    *,
    feed_client: FeedClient | None = None,
    http_client: SecHttpClient | None = None,
    today: date | None = None,
    now: datetime | None = None,
) -> int:
    """Publish one snapshot per month for the requested archive range.

    The in-progress month is fetched uncached: its cache rows are cleared
    before and after the fetch, so no partial payload is served or retained.
    """
    if options.start is None or options.end is None:
        raise ValueError("backfill requires a start and end month")
    months = iter_months(options.start, options.end)
    http = http_client or getattr(feed_client, "_http", None)
    client = feed_client
    if client is None:
        http = http or build_http_client()
        client = build_feed_client(http)
    fetched_at = now or datetime.now(UTC)
    current = today or date.today()
    in_progress = (current.year, current.month)
    paths = options.feeds_paths()
    rows = [
        KeyValueRow("command", "backfill"),
        KeyValueRow("months", str(len(months))),
    ]
    total_new = 0
    total_events = 0
    for year, month in months:
        uncached = (year, month) == in_progress and http is not None
        if uncached:
            http.clear_cache(url=structured_archive_url(year, month), vacuum=False)
        try:
            events = client.archive_month_events(year, month)
        finally:
            if uncached:
                http.clear_cache(url=structured_archive_url(year, month), vacuum=False)
        result = publish_events(
            paths,
            events,
            command=f"backfill:{year:04d}-{month:02d}",
            fetched_at=fetched_at,
            branch=options.branch,
        )
        total_new += result.new_rows
        total_events += len(events)
        rows.append(
            KeyValueRow(
                f"month_{year:04d}-{month:02d}",
                f"events={len(events)} new_rows={result.new_rows} "
                f"published={result.published} source={SOURCE_MONTHLY_ARCHIVE}",
            )
        )
    rows.append(KeyValueRow("total_events", str(total_events)))
    rows.append(KeyValueRow("total_new_rows", str(total_new)))
    rows.append(
        KeyValueRow("range", f"{format_month(months[0])}..{format_month(months[-1])}")
    )
    render_output(rows, title="Feeds Backfill")
    return 0


__all__ = ["cmd_backfill"]
