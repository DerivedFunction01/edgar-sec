"""Feed client: page iteration stop conditions and cross-feed dedupe."""

from __future__ import annotations

from datetime import UTC, datetime

from edgar_sec.domain.sec_urls import (
    current_filings_url,
    structured_archive_url,
    structured_feed_url,
)
from edgar_sec.engine.feeds.client import FeedClient, dedupe_events
from edgar_sec.engine.feeds.parser_atom import parse_atom_feed
from edgar_sec.engine.feeds.parser_rss import parse_live_feed
from tests.support import FakeSession, build_test_http, fixture_path

_EMPTY_FEED = b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'


def _client(session: FakeSession, **kwargs: object) -> FeedClient:
    return FeedClient(build_test_http(session), page_size=3, **kwargs)  # type: ignore[arg-type]


def _paged_session() -> FakeSession:
    session = FakeSession()
    session.register_bytes(
        current_filings_url(count=3, start=0),
        fixture_path("feeds/current_filings_atom.xml").read_bytes(),
    )
    session.register_bytes(current_filings_url(count=3, start=3), _EMPTY_FEED)
    return session


def test_walk_yields_deduped_events_until_an_empty_page() -> None:
    session = _paged_session()
    events = list(_client(session).iter_current_filings())
    # The fixture page's first two entries are co-filers of one accession.
    assert [event.accession_normalized for event in events] == [
        "000119312526452288",
        "000090883426000509",
    ]
    assert session.calls == [
        current_filings_url(count=3, start=0),
        current_filings_url(count=3, start=3),
    ]


def test_walk_stops_on_a_page_entirely_at_or_before_the_bound() -> None:
    session = _paged_session()
    bound = datetime(2026, 11, 7, 3, 0, tzinfo=UTC)
    events = list(_client(session).iter_current_filings(acceptance_after=bound))
    assert events == []
    assert session.calls == [current_filings_url(count=3, start=0)]


def test_walk_applies_the_bound_client_side_within_a_page() -> None:
    session = _paged_session()
    bound = datetime(2026, 11, 7, 2, 55, tzinfo=UTC)
    events = list(_client(session).iter_current_filings(acceptance_after=bound))
    assert [event.accession_normalized for event in events] == ["000119312526452288"]
    assert len(session.calls) == 2


def test_walk_respects_the_page_cap() -> None:
    session = _paged_session()
    events = list(_client(session, max_pages=1).iter_current_filings())
    assert len(events) == 2
    assert session.calls == [current_filings_url(count=3, start=0)]


def test_structured_events_merge_a_multi_feed_accession() -> None:
    session = FakeSession()
    for feed, fixture in (
        ("usgaap", "feeds/structured_usgaap.rss.xml"),
        ("inline", "feeds/structured_inline.rss.xml"),
        ("all", "feeds/structured_all.rss.xml"),
    ):
        session.register_bytes(
            structured_feed_url(feed), fixture_path(fixture).read_bytes()
        )
    events = _client(session).structured_events(("usgaap", "inline", "all"))
    assert len(events) == 4
    by_accession = {event.accession_normalized: event for event in events}
    assert by_accession["000119312526452129"].sources == ("usgaap", "inline", "all")
    assert by_accession["000149315226050546"].sources == ("usgaap",)


def test_archive_month_events_carry_the_archive_source() -> None:
    session = FakeSession()
    session.register_bytes(
        structured_archive_url(2026, 10),
        fixture_path("feeds/structured_archive_2026-10.xml").read_bytes(),
    )
    events = _client(session).archive_month_events(2026, 10)
    assert len(events) == 3
    assert all(event.sources == ("monthly_archive",) for event in events)


def test_dedupe_events_keeps_first_fields_and_all_sources() -> None:
    usgaap = parse_live_feed(
        fixture_path("feeds/structured_usgaap.rss.xml").read_bytes(), "usgaap"
    ).events
    inline = parse_live_feed(
        fixture_path("feeds/structured_inline.rss.xml").read_bytes(), "inline"
    ).events
    merged = dedupe_events([*usgaap, *inline])
    assert len(merged) == 4
    assert merged[0].sources == ("usgaap", "inline")


def test_parse_failures_accumulate_on_the_client() -> None:
    session = FakeSession()
    payload = (
        b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
        b"<entry><title>broken</title></entry></feed>"
    )
    session.register_bytes(current_filings_url(count=3, start=0), payload)
    session.register_bytes(current_filings_url(count=3, start=1), _EMPTY_FEED)
    client = _client(session)
    assert list(client.iter_current_filings()) == []
    assert len(client.parse_failures) == 1


def test_atom_fixture_outcome_feeds_the_walk_shape() -> None:
    outcome = parse_atom_feed(
        fixture_path("feeds/current_filings_atom.xml").read_bytes()
    )
    assert len(outcome.events) == 3
    assert outcome.parser_fingerprint == "feed-atom-v1"
