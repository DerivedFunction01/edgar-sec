"""Managed same-host SEC acquisition broker.

One broker process owns the single production SecHttpClient (rate limiter,
cache, failure ledger, metrics). Workers submit archive URLs over a Unix domain
socket and never construct their own SEC client, so all live requests share one
aggregate pace governed by settings.
"""

from __future__ import annotations

import json
import os
import socket
import struct
import threading
from pathlib import Path
from typing import Any

from edgar_sec.foundation.runtime.memory import reclaim
from edgar_sec.infra.sec_http.client import SecHttpClient
from edgar_sec.infra.sec_http.errors import (
    PermanentHttpError,
    ResponseTooLargeError,
    RetryExhausted,
)
from edgar_sec.infra.sec_http.metrics import HttpMetrics

PROTOCOL_VERSION = 1
_HEADER_STRUCT = struct.Struct("!I")
_HEADER_SIZE = _HEADER_STRUCT.size
_SOCKET_BACKLOG = 128
_READ_TIMEOUT_S = 30.0
HEALTHCHECK_URL = "healthcheck://broker"
_RECLAIM_BYTES_THRESHOLD = 512 * 1024 * 1024


class BrokerError(Exception):
    """Raised when a broker request cannot be satisfied."""


class BrokerRequestError(BrokerError):
    """A broker-reported failure for one archive URL."""


def _send_frame(sock: socket.socket, payload: bytes) -> None:
    sock.sendall(_HEADER_STRUCT.pack(len(payload)) + payload)


def _recv_exactly(sock: socket.socket, count: int) -> bytes:
    chunks: list[bytes] = []
    remaining = count
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise BrokerError("broker closed the connection mid-frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _recv_frame(sock: socket.socket) -> bytes:
    header = _recv_exactly(sock, _HEADER_SIZE)
    (length,) = _HEADER_STRUCT.unpack(header)
    if length < 0:
        raise BrokerError("broker sent a negative frame length")
    return _recv_exactly(sock, length)


def _json_dumps(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _json_loads(raw: bytes) -> dict[str, Any]:
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise BrokerError("broker sent a non-object JSON frame")
    return data


class SecBroker:
    """Server-side broker that owns one SEC client and serves fetch RPCs."""

    def __init__(
        self,
        *,
        socket_path: str | Path,
        http_client: SecHttpClient | Any | None = None,
        max_connections: int = 32,
    ) -> None:
        self.socket_path = Path(socket_path)
        self._max_connections = max(1, max_connections)
        self._client = http_client or SecHttpClient()
        self._metrics = getattr(self._client, "metrics", HttpMetrics())
        self._lock = threading.Lock()
        self._active = 0
        self._bytes_since_reclaim = 0
        self._semaphore = threading.Semaphore(self._max_connections)
        self._server: socket.socket | None = None
        self._stop = threading.Event()

    @property
    def metrics(self) -> HttpMetrics:
        return self._metrics

    def snapshot(self) -> dict[str, Any]:
        base = self._metrics.snapshot() if hasattr(self._metrics, "snapshot") else {}
        with self._lock:
            base["active_requests"] = self._active
        return base

    def fetch(self, archive_url: str, *, force_refresh: bool = False) -> dict[str, Any]:
        """Serve one archive fetch, returning a response dict."""
        if archive_url == HEALTHCHECK_URL:
            return {
                "status": "ok",
                "error": None,
                "payload_length": 0,
                "payload": b"",
            }
        peek = getattr(self._client, "peek_cache", None)
        if peek is not None and not force_refresh:
            peeked = peek(archive_url)
            if peeked is not None:
                if self._note_bytes(len(peeked)):
                    reclaim()
                return {
                    "status": "ok",
                    "error": None,
                    "payload_length": len(peeked),
                    "payload": peeked,
                }
        with self._semaphore:
            with self._lock:
                self._active += 1
            payload: bytes | None = None
            try:
                if force_refresh:
                    payload = self._client.get_bytes(archive_url, force_refresh=True)
                else:
                    payload = self._client.get_bytes(archive_url)
            except (PermanentHttpError, ResponseTooLargeError, RetryExhausted) as exc:
                return {
                    "status": "failed",
                    "error": str(exc) or type(exc).__name__,
                    "payload_length": 0,
                }
            except Exception as exc:  # noqa: BLE001
                return {
                    "status": "failed",
                    "error": str(exc) or type(exc).__name__,
                    "payload_length": 0,
                }
            finally:
                with self._lock:
                    self._active -= 1
            due_reclaim = self._note_bytes(len(payload) if payload else 0)
        if due_reclaim:
            reclaim()
        return {
            "status": "ok",
            "error": None,
            "payload_length": len(payload) if payload else 0,
            "payload": payload,
        }

    def _note_bytes(self, count: int) -> bool:
        with self._lock:
            self._bytes_since_reclaim += count
            if self._bytes_since_reclaim >= _RECLAIM_BYTES_THRESHOLD:
                self._bytes_since_reclaim = 0
                return True
            return False

    def handle_connection(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(_READ_TIMEOUT_S)
            while not self._stop.is_set():
                try:
                    request_raw = _recv_frame(conn)
                except BrokerError:
                    return
                request = _json_loads(request_raw)
                request_id = request.get("request_id")
                archive_url = request.get("archive_url")
                force_refresh = bool(request.get("force_refresh", False))
                if not isinstance(request_id, str) or not isinstance(archive_url, str):
                    response = {
                        "request_id": request_id,
                        "status": "failed",
                        "error": "malformed request: request_id and archive_url are required",
                        "payload_length": 0,
                    }
                    payload = b""
                else:
                    result = self.fetch(archive_url, force_refresh=force_refresh)
                    response = {
                        "request_id": request_id,
                        "status": result["status"],
                        "error": result.get("error"),
                        "payload_length": result["payload_length"],
                    }
                    payload = result.get("payload") or b""
                header = _json_dumps(response)
                try:
                    conn.sendall(_HEADER_STRUCT.pack(len(header)) + header)
                    if payload:
                        conn.sendall(bytes(payload))
                except OSError:
                    return
                finally:
                    result = None
                    response = None
                    payload = None
                    header = None
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def serve(self) -> None:
        """Bind, accept, and serve connections until stop is signaled."""
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(self.socket_path))
        server.listen(_SOCKET_BACKLOG)
        server.settimeout(0.5)
        self._server = server
        try:
            while not self._stop.is_set():
                try:
                    conn, _ = server.accept()
                except TimeoutError:
                    continue
                except OSError:
                    return
                thread = threading.Thread(
                    target=self.handle_connection, args=(conn,), daemon=True
                )
                thread.start()
        finally:
            self._server = None
            try:
                server.close()
            except OSError:
                pass
            try:
                self.socket_path.unlink()
            except FileNotFoundError:
                pass

    def stop(self) -> None:
        self._stop.set()
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass


class SecBrokerClient:
    """Worker-side client that routes SEC archive fetches through the broker."""

    def __init__(self, socket_path: str | Path) -> None:
        self.socket_path = Path(socket_path)
        self._local = threading.local()

    def __getstate__(self) -> dict[str, object]:
        return {"socket_path": self.socket_path}

    def __setstate__(self, state: dict[str, object]) -> None:
        self.socket_path = Path(state["socket_path"])  # type: ignore[arg-type]
        self._local = threading.local()

    @property
    def metrics(self) -> HttpMetrics | None:
        return None

    def _get_socket(self) -> socket.socket:
        sock = getattr(self._local, "sock", None)
        if sock is None:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(_READ_TIMEOUT_S)
            try:
                sock.connect(str(self.socket_path))
            except OSError:
                sock.close()
                raise
            self._local.sock = sock
        return sock

    def _reset_socket(self) -> None:
        sock = getattr(self._local, "sock", None)
        self._local.sock = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _exchange(self, request: bytes) -> tuple[dict[str, Any], bytes]:
        sock = self._get_socket()
        sock.sendall(_HEADER_STRUCT.pack(len(request)) + request)
        header_raw = _recv_exactly(sock, _HEADER_SIZE)
        (header_len,) = _HEADER_STRUCT.unpack(header_raw)
        header = _json_loads(_recv_exactly(sock, header_len))
        payload_length = int(header.get("payload_length", 0) or 0)
        payload = _recv_exactly(sock, payload_length) if payload_length else b""
        return header, payload

    def fetch(self, archive_url: str, *, force_refresh: bool = False) -> dict[str, Any]:
        """Fetch one archive URL through the broker."""
        request_id = os.urandom(8).hex()
        request = _json_dumps(
            {
                "request_id": request_id,
                "archive_url": archive_url,
                "force_refresh": force_refresh,
            }
        )
        header: dict[str, Any] | None = None
        payload = b""
        for attempt in (1, 2):
            try:
                header, payload = self._exchange(request)
                break
            except (OSError, BrokerError) as exc:
                self._reset_socket()
                if attempt == 2:
                    return {
                        "status": "failed",
                        "error": str(exc) or type(exc).__name__,
                        "payload": None,
                    }
        if header is None:
            return {
                "status": "failed",
                "error": "broker exchange did not complete",
                "payload": None,
            }
        if header.get("status") != "ok":
            return {
                "status": "failed",
                "error": header.get("error") or "broker reported failure",
                "payload": None,
            }
        return {"status": "ok", "error": None, "payload": payload}


__all__ = [
    "HEALTHCHECK_URL",
    "PROTOCOL_VERSION",
    "BrokerError",
    "BrokerRequestError",
    "SecBroker",
    "SecBrokerClient",
]
