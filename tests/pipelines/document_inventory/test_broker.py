"""Tests for the SEC index-page broker adapter."""

import pickle
from pathlib import Path

from edgar_sec.domain.document_inventory.models import IndexWorkItem
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.infra.broker.daemon import managed_broker
from edgar_sec.infra.sec_http.errors import RetryExhausted
from edgar_sec.infra.sec_http.metrics import HttpMetrics
from edgar_sec.pipelines.document_inventory.broker import (
    IndexFetchFailure,
    IndexPageBrokerClient,
)
from tests.support import fixture_path

INDEX_HTML = fixture_path("document_inventory_index_page.html").read_bytes()


def _item() -> IndexWorkItem:
    accession = AccessionNumber("0000000001-26-000001")
    url = f"https://www.sec.gov/Archives/edgar/data/1/{accession.normalized}/index.htm"
    return IndexWorkItem(accession, url)


class _FakeHttp:
    def __init__(self, pages=None, failing=None, error=None) -> None:
        self.pages = pages or {}
        self.failing = failing or set()
        self.error = error
        self.calls: list[str] = []
        self.metrics = HttpMetrics()

    def peek_cache(self, _url: str) -> None:
        return None

    def get_bytes(self, url: str, *, force_refresh: bool = False) -> bytes:
        self.calls.append(url)
        if url in self.failing:
            raise self.error or RuntimeError("transport failed")
        return self.pages[url]


def test_fetch_index_returns_exact_bytes(tmp_path: Path) -> None:
    item = _item()
    fake = _FakeHttp({item.index_url: INDEX_HTML})

    with managed_broker(tmp_path / "b.sock", http_client=fake):
        page = IndexPageBrokerClient(tmp_path / "b.sock").fetch_index(
            item.accession, item.index_url
        )

    assert not isinstance(page, IndexFetchFailure)
    assert page.html_bytes == INDEX_HTML
    assert page.response_size == len(INDEX_HTML)
    assert fake.calls == [item.index_url]


def test_fetch_index_maps_transport_failure(tmp_path: Path) -> None:
    item = _item()
    fake = _FakeHttp(
        failing={item.index_url},
        error=RetryExhausted(item.index_url, "429 too many requests", 429),
    )

    with managed_broker(tmp_path / "b.sock", http_client=fake):
        page = IndexPageBrokerClient(tmp_path / "b.sock").fetch_index(
            item.accession, item.index_url
        )

    assert isinstance(page, IndexFetchFailure)
    assert page.code == "fetch_failed"
    assert "retries exhausted" in page.detail


def test_broker_client_pickle_reconstructs_socket(tmp_path: Path) -> None:
    client = IndexPageBrokerClient(tmp_path / "b.sock")
    restored = pickle.loads(pickle.dumps(client))

    assert restored.socket_path == tmp_path / "b.sock"
    assert restored._client.socket_path == tmp_path / "b.sock"
