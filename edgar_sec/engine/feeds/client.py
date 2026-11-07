"""Feed client over an injected ``SecHttpClient``: streaming page iteration.

Pages are fetched, parsed, and yielded one at a time; the only walk state is
the set of accession keys already yielded, never events or payloads.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import datetime

from edgar_sec.domain.feeds.models import (
    FeedParseFailure,
    FeedParseOutcome,
    FilingEvent,
)
from edgar_sec.domain.sec_urls import (
    current_filings_url,
    structured_archive_url,
    structured_feed_url,
)
from edgar_sec.engine.feeds.parser_atom import parse_atom_feed
from edgar_sec.engine.feeds.parser_rss import parse_archive_month, parse_live_feed
from edgar_sec.foundation.runtime.settings.sec import DEFAULT_FEED_MAX_PAGES
from edgar_sec.infra.sec_http.client import SecHttpClient

DEFAULT_PAGE_SIZE = 100


def dedupe_events(events: Iterable[FilingEvent]) -> list[FilingEvent]:
    """Merge events by normalized accession, keeping first fields and all sources."""
    merged: dict[str, FilingEvent] = {}
    for event in events:
        existing = merged.get(event.accession_normalized)
        if existing is None:
            merged[event.accession_normalized] = event
            continue
        for source in event.sources:
            existing = existing.with_source(source)
        merged[event.accession_normalized] = existing
    return list(merged.values())


class FeedClient:
    """Fetches feed pages through the shared SEC transport and parses them."""

    def __init__(
        self,
        http_client: SecHttpClient,
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_pages: int = DEFAULT_FEED_MAX_PAGES,
    ) -> None:
        if page_size <= 0 or max_pages <= 0:
            raise ValueError("page_size and max_pages must be positive")
        self._http = http_client
        self.page_size = page_size
        self.max_pages = max_pages
        self.parse_failures: list[FeedParseFailure] = []

    def current_filings_page(
        self,
        *,
        form: str | None = None,
        cik: str | int | None = None,
        start: int = 0,
    ) -> FeedParseOutcome:
        """Fetch and parse one getcurrent Atom page at ``start``."""
        url = current_filings_url(form=form, cik=cik, count=self.page_size, start=start)
        outcome = parse_atom_feed(self._http.get_bytes(url, content_kind="xml"))
        self.parse_failures.extend(outcome.failures)
        return outcome

    def iter_current_filings(
        self,
        *,
        form: str | None = None,
        cik: str | int | None = None,
        acceptance_after: datetime | None = None,
    ) -> Iterator[FilingEvent]:
        """Yield events newer than ``acceptance_after``, page by page.

        Stops on an empty page, a page entirely at-or-before the bound, or
        the page cap; duplicates across pages are skipped by accession key.
        """
        seen: set[str] = set()
        start = 0
        for _page in range(self.max_pages):
            outcome = self.current_filings_page(form=form, cik=cik, start=start)
            if not outcome.events and not outcome.failures:
                return
            at_or_before = 0
            for event in outcome.events:
                if (
                    acceptance_after is not None
                    and event.acceptance_datetime is not None
                    and event.acceptance_datetime <= acceptance_after
                ):
                    at_or_before += 1
                    continue
                if event.accession_normalized in seen:
                    continue
                seen.add(event.accession_normalized)
                yield event
            if acceptance_after is not None and at_or_before == len(outcome.events):
                return
            start += len(outcome.events) + len(outcome.failures)

    def live_feed_events(self, feed: str) -> tuple[FilingEvent, ...]:
        """Fetch and parse one live structured-disclosure feed."""
        url = structured_feed_url(feed)
        outcome = parse_live_feed(self._http.get_bytes(url, content_kind="xml"), feed)
        self.parse_failures.extend(outcome.failures)
        return outcome.events

    def archive_month_events(self, year: int, month: int) -> tuple[FilingEvent, ...]:
        """Fetch and parse one monthly structured-disclosure archive."""
        url = structured_archive_url(year, month)
        outcome = parse_archive_month(
            self._http.get_bytes(url, content_kind="xml"), year, month
        )
        self.parse_failures.extend(outcome.failures)
        return outcome.events

    def structured_events(self, feeds: Iterable[str]) -> list[FilingEvent]:
        """Fetch the named live feeds and dedupe across them by accession."""
        events: list[FilingEvent] = []
        for feed in feeds:
            events.extend(self.live_feed_events(feed))
        return dedupe_events(events)


__all__ = ["DEFAULT_PAGE_SIZE", "FeedClient", "dedupe_events"]
