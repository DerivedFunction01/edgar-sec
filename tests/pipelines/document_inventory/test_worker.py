"""Tests for one-accession broker-backed processing."""

from pathlib import Path

from edgar_sec.domain.document_inventory.models import (
    IndexPageInput,
    IndexWorkItem,
    ParsedIndexPage,
    ParserDiagnostics,
    UnrecognizedIndexPage,
)
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.infra.broker.daemon import managed_broker
from edgar_sec.infra.sec_http.metrics import HttpMetrics
from edgar_sec.pipelines.document_inventory.broker import (
    IndexFetchFailure,
    IndexPageBrokerClient,
)
from edgar_sec.pipelines.document_inventory import worker as worker_module
from edgar_sec.pipelines.document_inventory.worker import (
    IndexWorkerFailure,
    process_accession,
)
from tests.support import fixture_path

INDEX_HTML = fixture_path("document_inventory_index_page.html").read_bytes()


def _item() -> IndexWorkItem:
    accession = AccessionNumber("0000000001-26-000001")
    url = f"https://www.sec.gov/Archives/edgar/data/1/{accession.normalized}/index.htm"
    return IndexWorkItem(accession, url)


class _FakeHttp:
    def __init__(self, pages: dict[str, bytes]) -> None:
        self.pages = pages
        self.metrics = HttpMetrics()

    def peek_cache(self, _url: str) -> None:
        return None

    def get_bytes(self, url: str, *, force_refresh: bool = False) -> bytes:
        return self.pages[url]


def test_process_accession_parses_fetched_page(tmp_path: Path) -> None:
    item = _item()
    fake = _FakeHttp({item.index_url: INDEX_HTML})

    with managed_broker(tmp_path / "b.sock", http_client=fake):
        result = process_accession(item, IndexPageBrokerClient(tmp_path / "b.sock"))

    assert isinstance(result, ParsedIndexPage)
    assert len(result.entries) == 3
    assert not hasattr(result, "html_bytes")


def test_parser_exception_becomes_worker_failure(tmp_path: Path, monkeypatch) -> None:
    item = _item()
    fake = _FakeHttp({item.index_url: INDEX_HTML})

    def explode(_page: IndexPageInput):
        raise RuntimeError("parser exploded")

    monkeypatch.setattr(worker_module, "parse_html_index", explode)
    with managed_broker(tmp_path / "b.sock", http_client=fake):
        result = process_accession(item, IndexPageBrokerClient(tmp_path / "b.sock"))

    assert isinstance(result, IndexWorkerFailure)
    assert result.code == "worker_error"
    assert "parser exploded" in result.detail


def test_dead_broker_becomes_fetch_failure(tmp_path: Path) -> None:
    item = _item()

    result = process_accession(item, IndexPageBrokerClient(tmp_path / "absent.sock"))

    assert isinstance(result, IndexFetchFailure)
    assert result.code == "fetch_failed"


def test_response_bytes_are_not_capped(tmp_path: Path, monkeypatch) -> None:
    item = _item()
    payload = b"<html><body><p>" + b"A" * 500_000 + b"</p></body></html>"
    fake = _FakeHttp({item.index_url: payload})
    captured: list[bytes] = []

    def capture(page: IndexPageInput) -> UnrecognizedIndexPage:
        captured.append(page.response_bytes)
        return UnrecognizedIndexPage(
            page.accession,
            page.source_url,
            "deadbeef",
            ParserDiagnostics((), 0),
        )

    monkeypatch.setattr(worker_module, "parse_html_index", capture)
    with managed_broker(tmp_path / "b.sock", http_client=fake):
        result = process_accession(item, IndexPageBrokerClient(tmp_path / "b.sock"))

    assert captured == [payload]
    assert isinstance(result, UnrecognizedIndexPage)


SUMMARY_URL = (
    "https://www.sec.gov/Archives/edgar/data/1/000000000126000001/FilingSummary.xml"
)
PACKAGE_URL = (
    "https://www.sec.gov/Archives/edgar/data/1/000000000126000001/"
    "0000000001-26-000001-xbrl.zip"
)
JSON_URL = "https://www.sec.gov/Archives/edgar/data/1/000000000126000001/index.json"


def _summary_item(**overrides) -> IndexWorkItem:
    accession = AccessionNumber("0000000001-26-000001")
    fields = {
        "vehicle": "summary",
        "archive_cik": "1",
        "primary_document": "acme10k.htm",
        "is_inline_xbrl": False,
        "form": "10-K",
    }
    fields.update(overrides)
    return IndexWorkItem(
        accession,
        f"https://www.sec.gov/Archives/edgar/data/1/{accession.normalized}/index.htm",
        **fields,
    )


def _package_bytes(members: dict[str, bytes]) -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


class _StubBroker:
    """In-memory broker double recording the exact fetch order."""

    def __init__(self, documents=None, failures=None) -> None:
        self.documents = documents or {}
        self.failures = failures or {}
        self.calls: list[str] = []

    def fetch_document(self, accession, url, *, force_refresh=False):
        from edgar_sec.pipelines.document_inventory.broker import DocumentEnvelope

        self.calls.append(url)
        if url in self.failures:
            status_code, detail = self.failures[url]
            return IndexFetchFailure(
                accession, "fetch_failed", detail, status_code=status_code
            )
        payload = self.documents[url]
        return DocumentEnvelope(accession, url, len(payload), payload)

    def fetch_index(self, accession, index_url, *, force_refresh=False):
        from edgar_sec.pipelines.document_inventory.broker import IndexPageEnvelope

        self.calls.append(index_url)
        return IndexPageEnvelope(accession, index_url, len(INDEX_HTML), INDEX_HTML)


def test_summary_vehicle_serves_enumerated_documents() -> None:
    from edgar_sec.domain.document_inventory.models import EnumeratedDocuments

    broker = _StubBroker(
        documents={SUMMARY_URL: fixture_path("filing_summary_classic.xml").read_bytes()}
    )
    result = process_accession(_summary_item(), broker)

    assert isinstance(result, EnumeratedDocuments)
    assert result.vehicle == "summary"
    assert result.source_url == SUMMARY_URL
    assert broker.calls == [SUMMARY_URL]


def test_package_fallback_on_summary_404() -> None:
    from edgar_sec.domain.document_inventory.models import EnumeratedDocuments

    broker = _StubBroker(
        documents={PACKAGE_URL: _package_bytes({"acme-20121231.xml": b"instance"})},
        failures={SUMMARY_URL: (404, "http_not_found")},
    )
    result = process_accession(_summary_item(), broker)

    assert isinstance(result, EnumeratedDocuments)
    assert result.vehicle == "package"
    assert broker.calls == [SUMMARY_URL, PACKAGE_URL]


def test_package_fallback_on_unrecognized_summary() -> None:
    from edgar_sec.domain.document_inventory.models import EnumeratedDocuments

    broker = _StubBroker(
        documents={
            SUMMARY_URL: fixture_path(
                "filing_summary_classic_no_input_files.xml"
            ).read_bytes(),
            PACKAGE_URL: _package_bytes({"acme-20121231.xsd": b"schema"}),
        }
    )
    result = process_accession(_summary_item(), broker)

    assert isinstance(result, EnumeratedDocuments)
    assert result.vehicle == "package"
    assert broker.calls == [SUMMARY_URL, PACKAGE_URL]


def test_index_fallback_when_both_vehicles_absent() -> None:
    item = _summary_item()
    broker = _StubBroker(
        failures={
            SUMMARY_URL: (404, "http_not_found"),
            PACKAGE_URL: (404, "missing"),
            JSON_URL: (404, "missing"),
        }
    )
    result = process_accession(item, broker)

    assert isinstance(result, ParsedIndexPage)
    assert broker.calls == [SUMMARY_URL, PACKAGE_URL, JSON_URL, item.index_url]


def test_index_json_serves_listing_before_html() -> None:
    import json as json_module

    payload = json_module.dumps(
        {
            "directory": {
                "item": [
                    {"name": "acme10k.htm", "last-modified": "2026-01-01", "size": "10"}
                ]
            }
        }
    ).encode("utf-8")
    item = _summary_item()
    broker = _StubBroker(
        documents={JSON_URL: payload},
        failures={SUMMARY_URL: (404, "http_not_found"), PACKAGE_URL: (404, "missing")},
    )
    result = process_accession(item, broker)

    assert isinstance(result, ParsedIndexPage)
    assert result.source_url == JSON_URL
    assert [entry.filename for entry in result.entries] == ["acme10k.htm"]
    assert broker.calls == [SUMMARY_URL, PACKAGE_URL, JSON_URL]


def test_index_json_unrecognized_falls_back_to_html() -> None:
    item = _summary_item()
    broker = _StubBroker(
        documents={JSON_URL: b"{}"},
        failures={SUMMARY_URL: (404, "http_not_found"), PACKAGE_URL: (404, "missing")},
    )
    result = process_accession(item, broker)

    assert isinstance(result, ParsedIndexPage)
    assert result.source_url == item.index_url
    assert broker.calls == [SUMMARY_URL, PACKAGE_URL, JSON_URL, item.index_url]


def test_throttled_summary_stops_the_chain() -> None:
    broker = _StubBroker(failures={SUMMARY_URL: (503, "throttled")})
    result = process_accession(_summary_item(), broker)

    assert isinstance(result, IndexFetchFailure)
    assert result.status_code == 503
    assert result.vehicle == "summary"
    assert broker.calls == [SUMMARY_URL]


def test_inline_summary_synthesizes_extracted_instance() -> None:
    from edgar_sec.domain.document_inventory.models import EnumeratedDocuments

    item = _summary_item(primary_document="acme-10k_20241231.htm", is_inline_xbrl=True)
    broker = _StubBroker(
        documents={SUMMARY_URL: fixture_path("filing_summary_inline.xml").read_bytes()}
    )
    result = process_accession(item, broker)

    assert isinstance(result, EnumeratedDocuments)
    filenames = {entry.filename for entry in result.entries}
    assert "acme-10k_20241231_htm.xml" in filenames


def test_inline_package_fallback_synthesizes_extracted_instance() -> None:
    from edgar_sec.domain.document_inventory.models import EnumeratedDocuments

    item = _summary_item(primary_document="acme-10k_20241231.htm", is_inline_xbrl=True)
    broker = _StubBroker(
        documents={
            PACKAGE_URL: _package_bytes(
                {
                    "acme-10k_20241231.htm": b"primary",
                    "acme-20241231.xsd": b"schema",
                }
            )
        },
        failures={SUMMARY_URL: (404, "http_not_found")},
    )
    result = process_accession(item, broker)

    assert isinstance(result, EnumeratedDocuments)
    assert result.vehicle == "package"
    filenames = {entry.filename for entry in result.entries}
    assert "acme-10k_20241231_htm.xml" in filenames
    assert not any(e.document_type == "EX-101.INS" for e in result.entries)
