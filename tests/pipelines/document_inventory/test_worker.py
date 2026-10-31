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
