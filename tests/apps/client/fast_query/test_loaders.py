"""Tests for fast-path attachment loading from the canonical row."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.apps.client.cache import DocumentCache
from edgar_sec.apps.client.fast_query.loaders import make_attachment_loader
from edgar_sec.domain.document.aggregate import FilingAggregate, FilingAttachment
from edgar_sec.domain.document.canonical import CanonicalAttachmentRow
from edgar_sec.domain.document_inventory.models import (
    IndexPageInput,
    ParsedIndexPage,
)
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.domain.sec_urls import index_url_for
from edgar_sec.engine.index_pages.parser import parse_html_index

_INDEX_HTML = b"""
<html>
<body>
<table summary="Document Format Files">
<tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th><th>Size</th></tr>
<tr><td>1</td><td>10-K</td><td><a href="aapl-20230930.htm">aapl-20230930.htm</a></td><td>10-K</td><td>1000</td></tr>
<tr><td>2</td><td>SUBSIDIARIES</td><td><a href="ex21.htm">ex21.htm</a></td><td>EX-21.1</td><td>200</td></tr>
<tr><td>3</td><td>GRAPHIC</td><td><a href="logo.png">logo.png</a></td><td>GRAPHIC</td><td>50</td></tr>
</table>
</body>
</html>
"""


def _identity(att: FilingAttachment) -> tuple:
    return (
        att.attachment_id,
        att.entry_id,
        att.sequence,
        att.document_type,
        att.filename,
        att.url,
        att.size,
        att.description,
        att.table_kind,
        att.role,
    )


def test_attachment_loader_hydrates_canonical_identity(tmp_path: Path) -> None:
    accession = AccessionNumber.from_any("0000320193-23-000106")
    cache = DocumentCache(db_path=tmp_path / "cache.sqlite")
    cache.put(
        accession=accession.raw,
        cik="320193",
        form="10-K",
        filename=f"{accession.raw}-index.html",
        content=_INDEX_HTML,
        content_type="text/html",
    )
    filing = FilingAggregate(
        accession=accession,
        primary_cik=Cik(320193),
        ciks=(Cik(320193),),
        form="10-K",
        filing_date="2023-11-03",
        primary_document_path="aapl-20230930.htm",
    )

    attachments = make_attachment_loader(cache)(filing)

    assert [a.sequence for a in attachments] == [1, 2, 3]
    assert [a.role for a in attachments] == ["primary", "exhibit", "graphic"]
    assert all(a.table_kind == "document_format" for a in attachments)
    assert all(a.entry_id for a in attachments)
    assert len({a.entry_id for a in attachments}) == 3
    assert all(a.attachment_id == a.entry_id for a in attachments)
    assert all(a.sha256 is None for a in attachments)

    parsed = parse_html_index(
        IndexPageInput(
            accession=accession,
            source_url=index_url_for(accession, Cik(320193)),
            response_bytes=_INDEX_HTML,
        )
    )
    assert isinstance(parsed, ParsedIndexPage)
    expected = [
        _identity(
            CanonicalAttachmentRow.from_inventory_entry(entry).to_attachment(
                form="10-K"
            )
        )
        for entry in parsed.entries
    ]
    assert [_identity(a) for a in attachments] == expected
