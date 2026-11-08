"""Tests for the facade earnings-exhibit surface."""

import gzip

from edgar_sec.apps.client.facade import Edgar
from edgar_sec.apps.client.surfaces import FeedSearchSurfaces
from edgar_sec.domain.document.aggregate import FilingAggregate, FilingAttachment
from edgar_sec.domain.identity import AccessionNumber, Cik
from tests.support import fixture_path


def test_facade_exposes_earnings_exhibit() -> None:
    """The earnings surface lives on the facade mixin, not the facade body."""
    assert Edgar.earnings_exhibit is FeedSearchSurfaces.earnings_exhibit


def test_earnings_exhibit_delegates_to_extractor() -> None:
    """The surface returns the extractor's result for a fixture filing."""
    raw = gzip.decompress(
        fixture_path("earnings/0001437749-14-013440/ex99-1.htm.gz").read_bytes()
    )
    attachment = FilingAttachment(
        attachment_id="1",
        document_type="EX-99.1",
        filename="ex99-1.htm",
        url="",
        fetcher=lambda a: raw,
    )
    filing = FilingAggregate(
        accession=AccessionNumber.from_any("0001437749-14-013440"),
        primary_cik=Cik(785956),
        ciks=(Cik(785956),),
        form="8-K",
        filing_date="2014-07-24",
        attachments=(attachment,),
    )
    result = FeedSearchSurfaces().earnings_exhibit(filing)
    assert result.exhibit is not None
    assert result.exhibit.filename == "ex99-1.htm"
    assert result.headline is not None
    assert result.headline.revenue is not None
    assert result.headline.revenue.value == "257,113"
