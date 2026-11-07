"""Atom parser: the live getcurrent fixture, reproduced field-for-field."""

from __future__ import annotations

from datetime import UTC, date, datetime

from edgar_sec.engine.feeds.parser_atom import parse_atom_feed
from edgar_sec.foundation.hashing import sha256_bytes
from tests.support import fixture_path

FIXTURE = "feeds/current_filings_atom.xml"


def _payload() -> bytes:
    return fixture_path(FIXTURE).read_bytes()


def test_fixture_entries_parse_field_for_field() -> None:
    outcome = parse_atom_feed(_payload())
    assert outcome.failures == ()
    assert outcome.source == "current_filings"
    assert outcome.payload_sha256 == sha256_bytes(_payload())
    assert len(outcome.events) == 3

    first = outcome.events[0]
    assert first.form == "4"
    assert first.company_name == "MAXFIELD JOSHUA H"
    assert int(first.cik) == 2027497
    assert first.filing_date == date(2026, 11, 6)
    assert str(first.accession) == "0001193125-26-452288"
    assert first.accession_normalized == "000119312526452288"
    assert first.acceptance_datetime == datetime(2026, 11, 7, 2, 55, 3, tzinfo=UTC)
    assert first.link == (
        "https://www.sec.gov/Archives/edgar/data/2027497/000119312526452288/"
        "0001193125-26-452288-index.htm"
    )
    assert first.sources == ("current_filings",)

    third = outcome.events[2]
    assert third.company_name == "Barrocas Mark"
    assert str(third.accession) == "0000908834-26-000509"
    assert third.acceptance_datetime == datetime(2026, 11, 7, 2, 54, 24, tzinfo=UTC)


def test_a_malformed_entry_is_a_failure_not_a_raise() -> None:
    payload = (
        b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
        b"<entry><title>not a filing title</title></entry>"
        b"</feed>"
    )
    outcome = parse_atom_feed(payload)
    assert outcome.events == ()
    assert len(outcome.failures) == 1
    assert outcome.failures[0].entry_index == 0


def test_a_malformed_payload_is_one_failure() -> None:
    outcome = parse_atom_feed(b"<feed><entry>")
    assert outcome.events == ()
    assert len(outcome.failures) == 1
    assert outcome.failures[0].entry_index == -1
