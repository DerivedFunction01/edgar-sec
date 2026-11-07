"""RSS parser: live-feed and archive fixtures, reproduced field-for-field."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from edgar_sec.engine.feeds.parser_rss import (
    parse_archive_month,
    parse_live_feed,
    parse_rss_feed,
)
from tests.support import fixture_path


def test_usgaap_fixture_items_parse_field_for_field() -> None:
    payload = fixture_path("feeds/structured_usgaap.rss.xml").read_bytes()
    outcome = parse_live_feed(payload, "usgaap")
    assert outcome.failures == ()
    assert len(outcome.events) == 3

    first = outcome.events[0]
    assert first.company_name == "SUI Group Holdings Ltd."
    assert int(first.cik) == 1425355
    assert first.form == "10-Q"
    assert first.filing_date == date(2026, 11, 6)
    assert str(first.accession) == "0001193125-26-452129"
    assert first.acceptance_datetime == datetime(2026, 11, 6, 22, 30, 32, tzinfo=UTC)
    assert first.link == (
        "https://www.sec.gov/Archives/edgar/data/1425355/000119312526452129/"
        "0001193125-26-452129-index.htm"
    )
    assert first.sources == ("usgaap",)


@pytest.mark.parametrize(
    ("fixture", "feed", "company", "form"),
    [
        (
            "feeds/structured_risk_return.rss.xml",
            "risk_return",
            "Elevation Series Trust",
            "485BPOS",
        ),
        (
            "feeds/structured_inline.rss.xml",
            "inline",
            "SUI Group Holdings Ltd.",
            "10-Q",
        ),
        ("feeds/structured_all.rss.xml", "all", "SUI Group Holdings Ltd.", "10-Q"),
    ],
)
def test_each_live_feed_fixture_parses(
    fixture: str, feed: str, company: str, form: str
) -> None:
    outcome = parse_live_feed(fixture_path(fixture).read_bytes(), feed)
    assert outcome.failures == ()
    assert len(outcome.events) == 3
    assert outcome.events[0].company_name == company
    assert outcome.events[0].form == form
    assert outcome.events[0].sources == (feed,)


def test_archive_month_fixture_uses_the_archive_adapter() -> None:
    payload = fixture_path("feeds/structured_archive_2026-10.xml").read_bytes()
    outcome = parse_archive_month(payload, 2026, 10)
    assert outcome.failures == ()
    assert len(outcome.events) == 3

    first = outcome.events[0]
    assert first.company_name == "MOBIX LABS, INC"
    assert int(first.cik) == 1855467
    assert first.form == "S-1"
    assert first.filing_date == date(2026, 10, 30)
    assert str(first.accession) == "0001493152-26-049479"
    # 17:31:58 EDT is 21:31:58 UTC.
    assert first.acceptance_datetime == datetime(2026, 10, 30, 21, 31, 58, tzinfo=UTC)
    assert first.sources == ("monthly_archive",)


def test_an_item_without_the_structured_block_is_a_failure() -> None:
    payload = (
        b'<?xml version="1.0"?><rss version="2.0"><channel>'
        b"<item><title>x</title><link>https://example.invalid/</link></item>"
        b"</channel></rss>"
    )
    outcome = parse_rss_feed(payload, "usgaap")
    assert outcome.events == ()
    assert len(outcome.failures) == 1


def test_unknown_feed_and_bad_month_are_refused() -> None:
    with pytest.raises(ValueError):
        parse_live_feed(b"<rss/>", "nope")
    with pytest.raises(ValueError):
        parse_archive_month(b"<rss/>", 2026, 13)
