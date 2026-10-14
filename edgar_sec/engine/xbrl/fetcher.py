"""Network fetcher resolving index pages and extracting linkbases."""

from __future__ import annotations

from collections.abc import Sequence

from edgar_sec.domain.document_inventory.models import (
    IndexPageInput,
    ParsedIndexPage,
)
from edgar_sec.domain.sec_urls import index_url_for
from edgar_sec.engine.index_pages.parser import parse_html_index
from edgar_sec.engine.xbrl.cohort import SeedFiling
from edgar_sec.engine.xbrl.discovery import (
    DiscoveredLinkbase,
    extract_filing_linkbases,
)
from edgar_sec.infra.sec_http.client import SecHttpClient


def fetch_filing_linkbases(
    client: SecHttpClient,
    filing: SeedFiling,
) -> tuple[DiscoveredLinkbase, ...]:
    """Fetch index page for a filing and extract discovered linkbases."""
    url = index_url_for(filing.accession, filing.cik)
    try:
        raw_bytes = client.get_bytes(url, content_kind="index_page")
    except Exception:
        return ()

    page_input = IndexPageInput(
        accession=filing.accession,
        source_url=url,
        response_bytes=raw_bytes,
    )
    outcome = parse_html_index(page_input)
    if not isinstance(outcome, ParsedIndexPage):
        return ()

    return extract_filing_linkbases(outcome, filing.cik)


def fetch_cohort_linkbases(
    client: SecHttpClient,
    cohort: Sequence[SeedFiling],
) -> tuple[DiscoveredLinkbase, ...]:
    """Fetch index pages across an entire filing cohort and collect linkbases."""
    results: list[DiscoveredLinkbase] = []
    for filing in cohort:
        linkbases = fetch_filing_linkbases(client, filing)
        results.extend(linkbases)
    return tuple(results)
