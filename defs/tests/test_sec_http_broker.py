"""Tests for the managed same-host SEC acquisition broker."""

from __future__ import annotations

import hashlib
import json
import pickle
import socket
import struct
import threading
import time
from pathlib import Path

import pytest

from defs.runtime.paths import resolve_paths
from defs.sec_http.broker import SecBroker, SecBrokerClient, _recv_exactly, _send_frame
from defs.sec_http.metrics import HttpMetrics


class _FakeHttpBytes:
    def __init__(self, payloads: dict[str, bytes]) -> None:
        self.payloads = payloads
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def get_bytes(self, url: str) -> bytes:
        with self._lock:
            self.calls.append(url)
        if url in self.payloads:
            return self.payloads[url]
        raise RuntimeError(f"404 Not Found: {url}")


class _FakeSecClient:
    def __init__(self, payloads: dict[str, bytes]) -> None:
        self.http = _FakeHttpBytes(payloads)
        self.metrics = HttpMetrics()

    def get_bytes(self, url: str) -> bytes:
        return self.http.get_bytes(url)


@pytest.fixture
def broker_paths(tmp_path: Path) -> Path:
    return tmp_path / "broker.sock"


def _start_server(
    socket_path: Path, payloads: dict[str, bytes]
) -> tuple[SecBroker, threading.Thread]:
    server = SecBroker(
        socket_path=socket_path,
        http_client=_FakeSecClient(payloads),
        max_connections=8,
    )
    thread = threading.Thread(target=server.serve, daemon=False)
    thread.start()
    client = SecBrokerClient(socket_path)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            result = client.fetch("healthcheck://broker")
            if isinstance(result, dict) and result.get("status") == "ok":
                return server, thread
        except Exception:  # noqa: BLE001 - probing liveness
            result = None
        time.sleep(0.05)
    server.stop()
    thread.join(timeout=5)
    raise RuntimeError("broker did not become ready")


def _stop_server(server: SecBroker, thread: threading.Thread) -> None:
    server.stop()
    thread.join(timeout=5)


def test_broker_fetch_returns_payload(broker_paths: Path) -> None:
    payloads = {"https://www.sec.gov/Archives/x/doc.htm": b"<html>ok</html>"}
    server, thread = _start_server(broker_paths, payloads)
    try:
        client = SecBrokerClient(broker_paths)
        result = client.fetch("https://www.sec.gov/Archives/x/doc.htm")
        assert result["status"] == "ok"
        assert result["payload"] == b"<html>ok</html>"
    finally:
        _stop_server(server, thread)


def test_broker_fetch_failure_reports_error(broker_paths: Path) -> None:
    server, thread = _start_server(broker_paths, {})
    try:
        client = SecBrokerClient(broker_paths)
        result = client.fetch("https://www.sec.gov/Archives/missing/doc.htm")
        assert result["status"] == "failed"
        assert result["error"]
        assert result["payload"] is None
    finally:
        _stop_server(server, thread)


def test_broker_concurrent_clients_share_one_limiter(broker_paths: Path) -> None:
    payloads = {
        f"https://www.sec.gov/Archives/doc{i}.htm": f"<p>{i}</p>".encode()
        for i in range(8)
    }
    server, thread = _start_server(broker_paths, payloads)
    try:
        barrier = threading.Barrier(8, timeout=10)
        results: list[dict] = []
        errors: list[Exception] = []

        def worker(i: int) -> None:
            try:
                client = SecBrokerClient(broker_paths)
                res = client.fetch(f"https://www.sec.gov/Archives/doc{i}.htm")
                barrier.wait()
                results.append(res)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert not errors
        assert len(results) == 8
        assert all(r["status"] == "ok" for r in results)
        # All requests were served by the single broker-owned client.
        assert len(server._client.http.calls) == 8
    finally:
        _stop_server(server, thread)


def test_broker_client_missing_socket_fails_cleanly(tmp_path: Path) -> None:
    client = SecBrokerClient(tmp_path / "does-not-exist.sock")
    result = client.fetch("https://www.sec.gov/Archives/x/doc.htm")
    assert result["status"] == "failed"
    assert result["error"]


def test_broker_client_can_be_pickled_for_process_workers(tmp_path: Path) -> None:
    socket_path = tmp_path / "broker.sock"
    restored = pickle.loads(pickle.dumps(SecBrokerClient(socket_path)))

    assert restored.socket_path == socket_path
    assert restored._local is not None


def test_broker_malformed_request_returns_error(broker_paths: Path) -> None:
    server, thread = _start_server(broker_paths, {})
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.connect(str(broker_paths))
            bad = json.dumps({"no_url": True}).encode("utf-8")
            _send_frame(sock, bad)
            header_raw = _recv_exactly(sock, 4)
            (length,) = struct.unpack("!I", header_raw)
            header = json.loads(_recv_exactly(sock, length).decode("utf-8"))
            assert header["status"] == "failed"
            assert header["error"]
    finally:
        _stop_server(server, thread)


def test_broker_paths_resolve_under_runtime_root() -> None:
    paths = resolve_paths().broker_paths()
    assert paths.socket_path.parent.name == "broker"
    assert paths.registry_path.name == "broker.json"
    assert paths.pid_path.name == "broker.pid"


def test_broker_cli_start_stop_status(tmp_path: Path) -> None:
    import importlib

    broker_cli = importlib.import_module("defs.sec_http.broker_cli")
    socket_path = tmp_path / "cli.sock"

    started = broker_cli.main(["start", "--socket", str(socket_path)])
    assert started == 0

    registry = json.loads((tmp_path / "broker.json").read_text(encoding="utf-8"))
    registry_payload = registry.get("broker", registry)
    assert isinstance(registry_payload.get("cache_dir"), str)
    assert registry_payload["cache_dir"]

    status = broker_cli.main(["status", "--socket", str(socket_path)])
    assert status == 0

    stopped = broker_cli.main(["stop", "--socket", str(socket_path)])
    assert stopped == 0

    status_after = broker_cli.main(["status", "--socket", str(socket_path)])
    assert status_after == 0


class _CountingBroker(SecBroker):
    """SecBroker variant counting accepted connections."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._conn_count = 0
        self._conn_lock = threading.Lock()

    def handle_connection(self, conn: socket.socket) -> None:
        with self._conn_lock:
            self._conn_count += 1
        super().handle_connection(conn)


def _start_counting_server(
    socket_path: Path, payloads: dict[str, bytes]
) -> tuple[_CountingBroker, threading.Thread]:
    server = _CountingBroker(
        socket_path=socket_path,
        http_client=_FakeSecClient(payloads),
        max_connections=8,
    )
    thread = threading.Thread(target=server.serve, daemon=False)
    thread.start()
    probe = SecBrokerClient(socket_path)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            result = probe.fetch("healthcheck://broker")
            if isinstance(result, dict) and result.get("status") == "ok":
                return server, thread
        except Exception:  # noqa: BLE001 - probing liveness
            result = None
        time.sleep(0.05)
    server.stop()
    thread.join(timeout=5)
    raise RuntimeError("broker did not become ready")


def test_broker_client_reuses_one_connection_for_sequential_fetches(
    broker_paths: Path,
) -> None:
    payloads = {
        f"https://www.sec.gov/Archives/doc{i}.htm": f"<p>{i}</p>".encode()
        for i in range(4)
    }
    server, thread = _start_counting_server(broker_paths, payloads)
    try:
        baseline = server._conn_count
        client = SecBrokerClient(broker_paths)
        for i in range(4):
            result = client.fetch(f"https://www.sec.gov/Archives/doc{i}.htm")
            assert result["status"] == "ok"
            assert result["payload"] == f"<p>{i}</p>".encode()
        # One persistent connection served all sequential requests.
        assert server._conn_count == baseline + 1
    finally:
        _stop_server(server, thread)


def test_broker_client_reconnects_after_broker_restart(broker_paths: Path) -> None:
    payloads = {"https://www.sec.gov/Archives/x/doc.htm": b"<html>ok</html>"}
    server, thread = _start_counting_server(broker_paths, payloads)
    client = SecBrokerClient(broker_paths)
    result = client.fetch("https://www.sec.gov/Archives/x/doc.htm")
    assert result["status"] == "ok"
    _stop_server(server, thread)

    server2, thread2 = _start_counting_server(broker_paths, payloads)
    try:
        result = client.fetch("https://www.sec.gov/Archives/x/doc.htm")
        assert result["status"] == "ok"
        assert result["payload"] == b"<html>ok</html>"
    finally:
        _stop_server(server2, thread2)


def test_broker_client_fails_when_broker_gone(broker_paths: Path) -> None:
    payloads = {"https://www.sec.gov/Archives/x/doc.htm": b"<html>ok</html>"}
    server, thread = _start_counting_server(broker_paths, payloads)
    client = SecBrokerClient(broker_paths)
    assert client.fetch("https://www.sec.gov/Archives/x/doc.htm")["status"] == "ok"
    _stop_server(server, thread)
    # A drained in-flight request may still succeed on the dying connection;
    # the next fetch must fail cleanly after the reconnect attempt.
    deadline = time.monotonic() + 5
    result = client.fetch("https://www.sec.gov/Archives/x/doc.htm")
    while time.monotonic() < deadline and result["status"] == "ok":
        result = client.fetch("https://www.sec.gov/Archives/x/doc.htm")
    assert result["status"] == "failed"
    assert result["payload"] is None


def test_broker_fast_path_serves_cache_hit_without_connection_slot(
    tmp_path: Path,
) -> None:
    """A warm cache hit must not queue behind paced requests holding slots."""
    from defs.sec_http.cache import SqlCache

    class _BlockingPeekClient:
        """Misses block inside ``get_bytes`` like paced requests; peek reads the cache."""

        def __init__(self) -> None:
            self.cache = SqlCache(tmp_path / "cache")
            self.metrics = HttpMetrics()
            self.in_request = threading.Event()
            self.release = threading.Event()

        def peek_cache(self, url: str) -> bytes | None:
            return self.cache.get(url)

        def get_bytes(self, url: str) -> bytes:
            self.in_request.set()
            assert self.release.wait(timeout=10)
            raise RuntimeError("aborted")

    client = _BlockingPeekClient()
    payload = b"cached-bytes"
    client.cache.put(
        "https://www.sec.gov/Archives/cached.htm",
        payload,
        hashlib.sha256(payload).hexdigest(),
        len(payload),
        "bytes",
    )
    broker = SecBroker(
        socket_path=tmp_path / "fast.sock",
        http_client=client,
        max_connections=1,
    )
    try:
        miss_result: dict = {}

        def miss() -> None:
            miss_result["r"] = broker.fetch("https://www.sec.gov/Archives/miss.htm")

        miss_thread = threading.Thread(target=miss)
        miss_thread.start()
        assert client.in_request.wait(timeout=5)

        hit_result: dict = {}

        def hit() -> None:
            hit_result["r"] = broker.fetch("https://www.sec.gov/Archives/cached.htm")

        hit_thread = threading.Thread(target=hit)
        hit_thread.start()
        hit_thread.join(timeout=5)
        assert not hit_thread.is_alive(), "cache hit blocked behind an occupied slot"
        assert hit_result["r"]["status"] == "ok"
        assert hit_result["r"]["payload"] == payload

        client.release.set()
        miss_thread.join(timeout=5)
        assert miss_result["r"]["status"] == "failed"
    finally:
        client.release.set()
        broker.stop()


def test_broker_cache_dir_prefers_registry_field(tmp_path: Path) -> None:
    import importlib

    from defs.runtime.paths import BrokerPaths

    broker_cli = importlib.import_module("defs.sec_http.broker_cli")
    paths = BrokerPaths(tmp_path)
    paths.registry_path.write_text(
        json.dumps({"broker": {"pid": 1, "cache_dir": str(tmp_path / "cache")}}),
        encoding="utf-8",
    )

    assert broker_cli.broker_cache_dir(paths) == tmp_path / "cache"


def test_broker_cache_dir_falls_back_to_runtime_resolution(tmp_path: Path) -> None:
    import importlib

    from defs.runtime.paths import BrokerPaths

    broker_cli = importlib.import_module("defs.sec_http.broker_cli")

    assert broker_cli.broker_cache_dir(BrokerPaths(tmp_path)) == (
        resolve_paths().cache_root
    )
