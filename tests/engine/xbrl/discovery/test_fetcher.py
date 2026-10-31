"""Tests for offline linkbase fetching using FakeSession test doubles."""

from edgar_sec.domain.sec_urls import index_url_for
from edgar_sec.engine.xbrl.discovery.cohort import load_seed_cohort
from edgar_sec.engine.xbrl.discovery.discovery import LinkbaseType
from edgar_sec.engine.xbrl.discovery.fetcher import (
    fetch_cohort_linkbases,
    fetch_filing_linkbases,
)
from tests.support import FakeSession, build_test_http, fixture_path


def test_fetch_filing_linkbases_offline() -> None:
    """Verify linkbase fetch with mock SEC index page response."""
    cohort = load_seed_cohort(fixture_path("xbrl/seed_cohort.json"))
    filing = cohort[0]
    expected_url = index_url_for(filing.accession, filing.cik)
    html_bytes = fixture_path("xbrl/msft_index_page.html").read_bytes()

    session = FakeSession()
    session.register_bytes(expected_url, html_bytes)
    client = build_test_http(session)

    linkbases = fetch_filing_linkbases(client, filing)
    assert len(linkbases) > 0
    assert any(lb.linkbase_type == LinkbaseType.CALCULATION for lb in linkbases)
    assert session.calls == [expected_url]


def test_fetch_cohort_linkbases_offline() -> None:
    """Verify batch cohort linkbase fetching with mock session."""
    cohort = load_seed_cohort(fixture_path("xbrl/seed_cohort.json"))
    filings = cohort[:2]
    html_bytes = fixture_path("xbrl/msft_index_page.html").read_bytes()

    session = FakeSession()
    for f in filings:
        session.register_bytes(index_url_for(f.accession, f.cik), html_bytes)
    client = build_test_http(session)

    discovered = fetch_cohort_linkbases(client, filings)
    assert len(discovered) > 0
    assert len(session.calls) == 2
