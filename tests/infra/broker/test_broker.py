from __future__ import annotations

import pickle
import threading
from pathlib import Path
from typing import Any

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
