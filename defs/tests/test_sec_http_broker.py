"""Tests for the managed same-host SEC acquisition broker."""

from __future__ import annotations

import json
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

    status = broker_cli.main(["status", "--socket", str(socket_path)])
    assert status == 0

    stopped = broker_cli.main(["stop", "--socket", str(socket_path)])
    assert stopped == 0

    status_after = broker_cli.main(["status", "--socket", str(socket_path)])
    assert status_after == 0
