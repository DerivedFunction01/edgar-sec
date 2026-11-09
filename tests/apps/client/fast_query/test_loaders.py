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
from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.domain.sec_urls import index_url_for
from edgar_sec.engine.document_processing.pdf import convert_pdf_to_text
from edgar_sec.engine.forms.render import render_document
from edgar_sec.engine.index_pages.parser import parse_html_index
from tests.support import make_pdf_bytes

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


_ACCESSION = AccessionNumber.from_any("0000320193-23-000106")


def _filing() -> FilingAggregate:
    return FilingAggregate(
        accession=_ACCESSION,
        primary_cik=Cik(320193),
        ciks=(Cik(320193),),
        form="10-K",
        filing_date="2023-11-03",
        primary_document_path="aapl-20230930.htm",
    )


def _cache_with_index(tmp_path: Path, index_html: bytes = _INDEX_HTML) -> DocumentCache:
    cache = DocumentCache(db_path=tmp_path / "cache.sqlite")
    cache.put(
        accession=_ACCESSION.raw,
        cik="320193",
        form="10-K",
        filename=f"{_ACCESSION.raw}-index.html",
        content=index_html,
        content_type="text/html",
    )
    return cache


class _CountingClient:
    """Fake SEC client recording every fetch; payloads served by URL."""

    def __init__(self) -> None:
        self.payloads: dict[str, bytes] = {}
        self.calls: list[str] = []

    def get_bytes(self, url: str) -> bytes | None:
        self.calls.append(url)
        return self.payloads.get(url)


def test_attachment_state_reads_cache_presence_without_http(tmp_path: Path) -> None:
    cache = _cache_with_index(tmp_path)
    builds: list[int] = []

    def factory() -> _CountingClient:
        builds.append(1)
        return _CountingClient()

    attachments = make_attachment_loader(cache, factory)(_filing())
    assert [a.state for a in attachments] == ["not_acquired"] * 3
    assert builds == []

    cache.put(
        accession=_ACCESSION.raw,
        cik="320193",
        form="10-K",
        filename="ex21.htm",
        content=b"<html>subs</html>",
        content_type="text/html",
    )
    by_name = {a.filename: a for a in attachments}
    assert by_name["ex21.htm"].state == "acquired"
    assert by_name["aapl-20230930.htm"].state == "not_acquired"
    assert builds == []


def test_content_fetches_and_caches_exactly_once(tmp_path: Path) -> None:
    cache = _cache_with_index(tmp_path)
    client = _CountingClient()
    attachments = make_attachment_loader(cache, lambda: client)(_filing())
    att = next(a for a in attachments if a.filename == "ex21.htm")
    payload = b"<html>SUBSIDIARIES</html>"
    client.payloads[att.url] = payload

    assert att.state == "not_acquired"
    assert att.content() == payload
    assert client.calls == [att.url]
    assert att.content() == payload
    assert client.calls == [att.url]
    assert cache.get(_ACCESSION.raw, "ex21.htm") == payload
    assert att.state == "acquired"


_RENDER_INDEX_HTML = b"""
<html>
<body>
<table summary="Document Format Files">
<tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th><th>Size</th></tr>
<tr><td>1</td><td>PRESS RELEASE</td><td><a href="ex99.htm">ex99.htm</a></td><td>EX-99.1</td><td>200</td></tr>
<tr><td>2</td><td>PRESS RELEASE PDF</td><td><a href="ex99.pdf">ex99.pdf</a></td><td>EX-99.1</td><td>200</td></tr>
</table>
</body>
</html>
"""


def test_rendered_text_agrees_with_render_surface_and_routes_pdf(
    tmp_path: Path,
) -> None:
    cache = _cache_with_index(tmp_path, _RENDER_INDEX_HTML)
    html_payload = b"<html><body><p>Quarterly results improved.</p></body></html>"
    pdf_payload = make_pdf_bytes([" ".join(["Filed exhibit text."] * 12)])
    cache.put(_ACCESSION.raw, "320193", "10-K", "ex99.htm", html_payload)
    cache.put(_ACCESSION.raw, "320193", "10-K", "ex99.pdf", pdf_payload)

    attachments = make_attachment_loader(cache)(_filing())
    by_name = {a.filename: a for a in attachments}

    html_att = by_name["ex99.htm"]
    expected = render_document(
        html_payload,
        form="EX-99.1",
        filename="ex99.htm",
        operation=AcquisitionOperation.RENDER_TO_TXT,
    )
    assert html_att.rendered_text() == expected
    assert html_att.rendered_text() != html_att.text()

    pdf_att = by_name["ex99.pdf"]
    assert pdf_att.rendered_text() == convert_pdf_to_text(pdf_payload).text
    assert "Filed exhibit text." in (pdf_att.rendered_text() or "")
