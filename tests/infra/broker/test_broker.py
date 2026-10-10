from __future__ import annotations

import hashlib
import json
import pickle
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from edgar_sec.infra.broker.daemon import managed_broker
from edgar_sec.infra.broker.sec_broker import SecBrokerClient
from edgar_sec.infra.sec_http.metrics import HttpMetrics


class _FakeHttpClient:
    def __init__(self, payloads: dict[str, bytes]) -> None:
        self.payloads = payloads
        self.calls: list[str] = []
        self._lock = threading.Lock()
        self.metrics = HttpMetrics()

    def peek_cache(self, url: str) -> bytes | None:
        if url.endswith(".cached"):
            return self.payloads.get(url)
        return None

    def get_bytes(self, url: str, *, force_refresh: bool = False) -> bytes:
        with self._lock:
            self.calls.append(url)
        if url in self.payloads:
            return self.payloads[url]
        raise RuntimeError(f"404 Not Found: {url}")


class _FakeStreamHttpClient(_FakeHttpClient):
    def __init__(
        self,
        body: bytes,
        *,
        failure: str | None = None,
        final_url: str | None = None,
    ) -> None:
        super().__init__({})
        self.body = body
        self.failure = failure
        self.final_url = final_url
        self.stream_calls: list[tuple[str, Path, int]] = []

    def stream_to_file(
        self,
        url: str,
        destination: Path,
        *,
        max_response_bytes: int,
        validate_redirect: Any,
    ) -> Any:
        self.stream_calls.append((url, destination, max_response_bytes))
        if self.failure:
            destination.write_bytes(b"partial")
            return SimpleNamespace(
                code=self.failure,
                retryable=False,
                http_status=None,
                final_url=None,
            )
        destination.write_bytes(self.body)
        validate_redirect(url)
        final_url = self.final_url or url
        return SimpleNamespace(
            status_code=200,
            requested_url=url,
            final_url=final_url,
            sha256=hashlib.sha256(self.body).hexdigest(),
            byte_size=len(self.body),
            content_type="text/html",
            content_encoding="gzip",
        )


def test_managed_broker_lifecycle_and_fetch(tmp_path: Path) -> None:
    socket_path = tmp_path / "broker.sock"
    payloads = {
        "https://www.sec.gov/Archives/x/doc1.htm": b"<html>doc1</html>",
        "https://www.sec.gov/Archives/x/doc2.cached": b"<html>doc2 cached</html>",
    }
    fake_http = _FakeHttpClient(payloads)

    with managed_broker(socket_path, http_client=fake_http) as client:
        res1 = client.fetch("https://www.sec.gov/Archives/x/doc1.htm")
        assert res1["status"] == "ok"
        assert res1["payload"] == b"<html>doc1</html>"
        assert fake_http.calls == ["https://www.sec.gov/Archives/x/doc1.htm"]

        res2 = client.fetch("https://www.sec.gov/Archives/x/doc2.cached")
        assert res2["status"] == "ok"
        assert res2["payload"] == b"<html>doc2 cached</html>"
        assert len(fake_http.calls) == 1

        res3 = client.fetch("https://www.sec.gov/Archives/missing.htm")
        assert res3["status"] == "failed"
        assert "404" in res3["error"]


def test_broker_concurrent_workers(tmp_path: Path) -> None:
    socket_path = tmp_path / "broker_concurrent.sock"
    payloads = {
        f"https://www.sec.gov/Archives/doc_{i}.htm": f"content_{i}".encode()
        for i in range(10)
    }
    fake_http = _FakeHttpClient(payloads)

    with managed_broker(socket_path, http_client=fake_http, max_connections=8) as _:
        results: list[dict[str, Any]] = []
        errors: list[Exception] = []

        def worker_task(idx: int) -> None:
            try:
                worker_client = SecBrokerClient(socket_path)
                res = worker_client.fetch(f"https://www.sec.gov/Archives/doc_{idx}.htm")
                results.append(res)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker_task, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        assert not errors
        assert len(results) == 10
        assert all(r["status"] == "ok" for r in results)


def test_broker_client_pickle(tmp_path: Path) -> None:
    socket_path = tmp_path / "broker.sock"
    client = SecBrokerClient(socket_path)
    pickled = pickle.dumps(client)
    restored = pickle.loads(pickled)

    assert restored.socket_path == socket_path
    assert restored._local is not None


def test_broker_client_close_resets_its_thread_socket() -> None:
    class Socket:
        closed = False

        def close(self) -> None:
            self.closed = True

    client = SecBrokerClient("unused.sock")
    connection = Socket()
    client._local.sock = connection

    client.close()

    assert connection.closed
    assert client._local.sock is None


def test_streamed_broker_writes_file_and_sends_metadata_only(
    tmp_path: Path,
) -> None:
    socket_path = tmp_path / "stream.sock"
    staging_root = tmp_path / "owner-stage"
    url = "https://www.sec.gov/Archives/edgar/data/2/000000000123000001/doc.htm"
    body = b"large body must remain on disk"
    fake_http = _FakeStreamHttpClient(body)

    with managed_broker(socket_path, http_client=fake_http) as client:
        frames: list[tuple[dict[str, Any], bytes]] = []
        exchange = client._exchange

        def capture_exchange(request: bytes) -> tuple[dict[str, Any], bytes]:
            result = exchange(request)
            frames.append(result)
            return result

        client._exchange = capture_exchange  # type: ignore[method-assign]
        result = client.stream_to_file(
            url,
            max_response_bytes=1024,
            accession_cik=2,
            accession_number="0000000001-23-000001",
            staging_root=staging_root,
        )

    assert result.status == "ok"
    assert result.path is not None
    assert result.path.parent == staging_root.resolve()
    assert result.path.name.startswith("sec-stream-")
    assert result.path.read_bytes() == body
    assert result.sha256 == hashlib.sha256(body).hexdigest()
    assert result.size == len(body)
    assert result.requested_url == url
    assert result.final_url == url
    assert result.status_code == 200
    assert result.content_type == "text/html"
    assert result.content_encoding == "gzip"
    assert len(fake_http.stream_calls) == 1

    header, payload = frames[0]
    assert payload == b""
    assert set(header) == {
        "request_id",
        "status",
        "path",
        "sha256",
        "size",
        "requested_url",
        "final_url",
        "status_code",
        "content_type",
        "content_encoding",
        "error_code",
        "retryable",
    }
    assert body not in json.dumps(header).encode()


def test_streamed_broker_returns_typed_failure_and_removes_partial_file(
    tmp_path: Path,
) -> None:
    socket_path = tmp_path / "stream-failure.sock"
    url = "https://www.sec.gov/Archives/edgar/data/1/000000000123000001/doc.htm"
    fake_http = _FakeStreamHttpClient(b"", failure="response_too_large")

    with managed_broker(socket_path, http_client=fake_http) as client:
        result = client.stream_to_file(
            url,
            max_response_bytes=1024,
            accession_cik=1,
            accession_number="0000000001-23-000001",
            staging_root=tmp_path / "failed-stage",
        )

    assert result.status == "failed"
    assert result.path is None
    assert result.error_code == "response_too_large"
    assert result.retryable is False
    assert list((tmp_path / "failed-stage").iterdir()) == []


def test_streamed_broker_rejects_invalid_scope_and_relative_staging_root(
    tmp_path: Path,
) -> None:
    socket_path = tmp_path / "stream-invalid.sock"
    fake_http = _FakeStreamHttpClient(b"unused")
    url = "https://www.sec.gov/Archives/edgar/data/1/000000000123000002/doc.htm"
    wrong_cik_url = (
        "https://www.sec.gov/Archives/edgar/data/1/000000000123000001/doc.htm"
    )

    with managed_broker(socket_path, http_client=fake_http) as client:
        bad_scope = client.stream_to_file(
            url,
            max_response_bytes=1024,
            accession_cik=1,
            accession_number="0000000001-23-000001",
        )
        bad_cik = client.stream_to_file(
            wrong_cik_url,
            max_response_bytes=1024,
            accession_cik=2,
            accession_number="0000000001-23-000001",
        )
        bad_root = client.stream_to_file(
            wrong_cik_url,
            max_response_bytes=1024,
            accession_cik=1,
            accession_number="0000000001-23-000001",
            staging_root="../../outside",
        )

    assert bad_scope.status == "failed"
    assert bad_scope.error_code == "invalid_scope"
    assert bad_cik.status == "failed"
    assert bad_cik.error_code == "invalid_scope"
    assert bad_root.status == "failed"
    assert bad_root.error_code == "invalid_path"
    assert fake_http.stream_calls == []


def test_streamed_broker_rejects_final_url_outside_accession_scope(
    tmp_path: Path,
) -> None:
    socket_path = tmp_path / "stream-redirect.sock"
    url = "https://www.sec.gov/Archives/edgar/data/1/000000000123000001/doc.htm"
    fake_http = _FakeStreamHttpClient(
        b"must be removed",
        final_url="https://www.sec.gov/Archives/edgar/data/1/000000000123000001/../doc.htm",
    )

    with managed_broker(socket_path, http_client=fake_http) as client:
        result = client.stream_to_file(
            url,
            max_response_bytes=1024,
            accession_cik=1,
            accession_number="0000000001-23-000001",
            staging_root=tmp_path / "redirect-stage",
        )

    assert result.status == "failed"
    assert result.error_code == "unsafe_redirect"
    assert list((tmp_path / "redirect-stage").iterdir()) == []


def test_streamed_broker_rejects_ipc_destination_outside_staging_root(
    tmp_path: Path,
) -> None:
    socket_path = tmp_path / "stream-path.sock"
    fake_http = _FakeStreamHttpClient(b"unused")
    with managed_broker(socket_path, http_client=fake_http) as client:
        response, body = client._exchange(
            json.dumps(
                {
                    "operation": "stream_to_file",
                    "request_id": "bad-destination",
                    "url": "https://www.sec.gov/Archives/edgar/data/1/000000000123000001/doc.htm",
                    "max_response_bytes": 1024,
                    "accession_cik": 1,
                    "accession_number": "0000000001-23-000001",
                    "staging_root": str(tmp_path / "stage"),
                    "destination": str(tmp_path / "escaped-body"),
                }
            ).encode()
        )

    assert body == b""
    assert response["status"] == "failed"
    assert response["error_code"] == "invalid_request"
    assert not (tmp_path / "escaped-body").exists()
    assert fake_http.stream_calls == []
