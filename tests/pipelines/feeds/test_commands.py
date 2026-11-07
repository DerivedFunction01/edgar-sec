"""Feeds commands over the Step 2 fixtures: run, backfill, status."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from edgar_sec.domain.feeds.models import STRUCTURED_FEED_SOURCES
from edgar_sec.domain.sec_urls import structured_archive_url, structured_feed_url
from edgar_sec.engine.feeds.client import FeedClient, dedupe_events
from edgar_sec.engine.feeds.parser_rss import parse_live_feed
from edgar_sec.pipelines.feeds.commands.backfill import cmd_backfill
from edgar_sec.pipelines.feeds.commands.run import cmd_run
from edgar_sec.pipelines.feeds.commands.status import cmd_status
from edgar_sec.pipelines.feeds.ledger import ledger_stats, ledger_tip
from edgar_sec.pipelines.feeds.options import feeds_options
from edgar_sec.pipelines.feeds.paths import resolve_feeds_paths
from tests.support import FakeSession, build_test_http, fixture_path

_FIXTURES = {
    "usgaap": "feeds/structured_usgaap.rss.xml",
    "risk_return": "feeds/structured_risk_return.rss.xml",
    "inline": "feeds/structured_inline.rss.xml",
    "all": "feeds/structured_all.rss.xml",
}


def _live_session() -> FakeSession:
    session = FakeSession()
    for feed, fixture in _FIXTURES.items():
        session.register_bytes(
            structured_feed_url(feed), fixture_path(fixture).read_bytes()
        )
    return session


def _expected_live_rows() -> tuple[int, dict[str, int]]:
    events = []
    for feed, fixture in _FIXTURES.items():
        events.extend(parse_live_feed(fixture_path(fixture).read_bytes(), feed).events)
    deduped = dedupe_events(events)
    per_source: dict[str, int] = {}
    for event in deduped:
        for source in event.sources:
            per_source[source] = per_source.get(source, 0) + 1
    return sum(per_source.values()), per_source


def test_run_publishes_the_four_live_feeds_reconciled(tmp_path: Path) -> None:
    client = FeedClient(build_test_http(_live_session()))
    options = feeds_options(artifacts_root=tmp_path)
    assert cmd_run(options, feed_client=client) == 0
    expected_rows, expected_per_source = _expected_live_rows()
    stats = ledger_stats(resolve_feeds_paths(tmp_path))
    assert stats is not None
    assert stats.total_rows == expected_rows
    assert {row.source: row.row_count for row in stats.per_source} == (
        expected_per_source
    )
    assert set(expected_per_source) == set(STRUCTURED_FEED_SOURCES)


def test_second_run_is_a_noop_and_the_tip_does_not_move(
    tmp_path: Path,
) -> None:
    options = feeds_options(artifacts_root=tmp_path)
    cmd_run(options, feed_client=FeedClient(build_test_http(_live_session())))
    paths = resolve_feeds_paths(tmp_path)
    tip_after_first = ledger_tip(paths)
    cmd_run(options, feed_client=FeedClient(build_test_http(_live_session())))
    assert ledger_tip(paths) == tip_after_first


def _archive_session() -> FakeSession:
    session = FakeSession()
    session.register_bytes(
        structured_archive_url(2026, 10),
        fixture_path("feeds/structured_archive_2026-10.xml").read_bytes(),
    )
    return session


def test_backfill_publishes_one_archive_month(tmp_path: Path) -> None:
    client = FeedClient(build_test_http(_archive_session()))
    options = feeds_options(artifacts_root=tmp_path, start=(2026, 10), end=(2026, 10))
    assert cmd_backfill(options, feed_client=client, today=date(2026, 11, 7)) == 0
    stats = ledger_stats(resolve_feeds_paths(tmp_path))
    assert stats is not None
    assert stats.total_rows == 3
    assert {row.source: row.row_count for row in stats.per_source} == {
        "monthly_archive": 3
    }
    assert cmd_backfill(options, feed_client=client, today=date(2026, 11, 7)) == 0
    stats_after = ledger_stats(resolve_feeds_paths(tmp_path))
    assert stats_after is not None
    assert stats_after.total_rows == 3
    assert stats_after.tip_snapshot_id == stats.tip_snapshot_id


class _RecordingHttp:
    """Records cache clears; the feed client rides a separate test HTTP."""

    def __init__(self) -> None:
        self.cleared: list[str] = []

    def clear_cache(self, *, url: str | None = None, vacuum: bool = True) -> int:
        self.cleared.append(str(url))
        return 0


def test_backfill_fetches_the_in_progress_month_uncached(
    tmp_path: Path,
) -> None:
    http = _RecordingHttp()
    client = FeedClient(build_test_http(_archive_session()))
    options = feeds_options(artifacts_root=tmp_path, start=(2026, 10), end=(2026, 10))
    assert (
        cmd_backfill(
            options,
            feed_client=client,
            http_client=http,  # type: ignore[arg-type]
            today=date(2026, 10, 15),
        )
        == 0
    )
    assert http.cleared == [structured_archive_url(2026, 10)] * 2


def test_status_reports_absence_without_a_ledger(tmp_path: Path) -> None:
    options = feeds_options(artifacts_root=tmp_path)
    assert cmd_status(options) == 0
    assert ledger_stats(resolve_feeds_paths(tmp_path)) is None
