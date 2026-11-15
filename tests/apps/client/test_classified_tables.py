"""Facade classified tables: the fast path over context production."""

from __future__ import annotations

from edgar_sec.apps.client.classified_tables import classified_tables_fast
from edgar_sec.apps.client.content_cache import ContentCache
from edgar_sec.domain.document.aggregate import FilingAggregate
from edgar_sec.domain.identity import AccessionNumber, Cik

_HTML_10K = b"""<html><body>
<p>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</p>
<p>FORM 10-K</p>
<p>ACME CORPORATION</p>
<p>PART I</p>
<p>ITEM 1. BUSINESS</p>
<p>Acme is a leading provider of widgets.</p>
<table><tr><td>Cash</td><td>100</td></tr><tr><td>Total assets</td><td>500</td></tr></table>
<p>SIGNATURES</p>
<p>Pursuant to the requirements of Section 13 of the Act, signed below.</p>
<table><tr><td>/s/ Jane Doe</td><td>Chief Executive Officer</td></tr></table>
</body></html>"""


def _filing() -> FilingAggregate:
    return FilingAggregate(
        accession=AccessionNumber.from_any("0000000000-24-000001"),
        primary_cik=Cik(1),
        ciks=(Cik(1),),
        form="10-K",
        filing_date="2024-03-01",
        primary_document_path="acme.htm",
        fetcher=lambda filing: _HTML_10K,
    )


def test_fast_path_classifies_and_caches() -> None:
    cache = ContentCache(64 * 1024 * 1024)
    filing = _filing()
    rows = classified_tables_fast(cache, filing)
    assert rows
    assert all(row.source_document == "primary" for row in rows)
    closing = rows[-1]
    assert closing.tier == "genre_refusal"
    assert closing.family == "other"
    again = classified_tables_fast(cache, filing)
    assert again == rows
    assert len(cache) == 1


def test_fast_path_empty_when_no_payload() -> None:
    cache = ContentCache(64 * 1024 * 1024)
    filing = FilingAggregate(
        accession=AccessionNumber.from_any("0000000000-24-000002"),
        primary_cik=Cik(1),
        ciks=(Cik(1),),
        form="10-K",
        filing_date="2024-03-01",
    )
    assert classified_tables_fast(cache, filing) == ()
