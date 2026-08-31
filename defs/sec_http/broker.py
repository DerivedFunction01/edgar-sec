"""Managed same-host SEC acquisition broker.

One broker process owns the single production ``SecHttpClient`` (rate
limiter, cache, failure ledger, metrics). Phase 2.5 production workers
submit archive URLs over a Unix-domain socket and never construct their own
SEC client, so all live requests share one aggregate pace.

Wire protocol (length-prefixed JSON frames):

Request header (4 bytes big-endian length) + JSON body::

    {"request_id": str, "archive_url": str}

Response header (4 bytes big-endian length) + JSON header + optional raw
payload::

    {"request_id": str, "status": "ok"|"failed", "error": str | None,
     "payload_length": int}

followed by ``payload_length`` raw bytes when status is "ok".
"""

from __future__ import annotations

import json
import os
import socket
import struct
import threading
from pathlib import Path
from typing import Any

from .client import SecHttpClient, make_sec_http_client
from .errors import PermanentHttpError, ResponseTooLargeError, RetryExhausted
from .metrics import HttpMetrics

PROTOCOL_VERSION = 1
_HEADER_STRUCT = struct.Struct("!I")
_HEADER_SIZE = _HEADER_STRUCT.size
_SOCKET_BACKLOG = 128
_READ_TIMEOUT_S = 30.0
HEALTHCHECK_URL = "healthcheck://broker"


class BrokerError(Exception):
    """Raised when a broker request cannot be satisfied."""


class BrokerRequestError(BrokerError):
    """A broker-reported failure for one archive URL."""


# --------------------------------------------------------------------- framing


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


# --------------------------------------------------------------------- broker


class SecBroker:
    """Server-side broker that owns one SEC client and serves fetch RPCs."""

    def __init__(
        self,
        *,
        socket_path: str | Path,
        http_client: SecHttpClient | None = None,
        max_connections: int = 16,
    ) -> None:
        self.socket_path = Path(socket_path)
        self._client = http_client or make_sec_http_client()
        self._metrics = self._client.metrics
        self._lock = threading.Lock()
        self._active = 0
        self._max_connections = max(1, max_connections)
        self._semaphore = threading.Semaphore(self._max_connections)
        self._server: socket.socket | None = None
        self._stop = threading.Event()

    @property
    def metrics(self) -> HttpMetrics:
        return self._metrics

    def snapshot(self) -> dict[str, Any]:
        base = self._metrics.snapshot()
        with self._lock:
            base["active_requests"] = self._active
        return base

    def fetch(self, archive_url: str) -> dict[str, Any]:
        """Serve one archive fetch, returning a response dict."""
        if archive_url == HEALTHCHECK_URL:
            return {
                "status": "ok",
                "error": None,
                "payload_length": 0,
                "payload": b"",
            }
        with self._semaphore:
            with self._lock:
                self._active += 1
            try:
                payload = self._client.get_bytes(archive_url)
            except (PermanentHttpError, ResponseTooLargeError, RetryExhausted) as exc:
                return {
                    "status": "failed",
                    "error": str(exc) or type(exc).__name__,
                    "payload_length": 0,
                }
            except Exception as exc:  # noqa: BLE001 - any client error is a per-document failure
                return {
                    "status": "failed",
                    "error": str(exc) or type(exc).__name__,
                    "payload_length": 0,
                }
            finally:
                with self._lock:
                    self._active -= 1
        return {
            "status": "ok",
            "error": None,
            "payload_length": len(payload),
            "payload": payload,
        }

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
                if not isinstance(request_id, str) or not isinstance(archive_url, str):
                    response = {
                        "request_id": request_id,
                        "status": "failed",
                        "error": "malformed request: request_id and archive_url are required",
                        "payload_length": 0,
                    }
                    payload = b""
                else:
                    result = self.fetch(archive_url)
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
                except OSError:
                    return
                if payload:
                    try:
                        conn.sendall(bytes(payload))
                    except OSError:
                        return
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def serve(self) -> None:
        """Bind, accept, and serve connections until ``stop`` is signaled."""
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


# --------------------------------------------------------------------- client


class SecBrokerClient:
    """Worker-side ``ArchiveFetcher`` that routes fetches through the broker."""

    def __init__(self, socket_path: str | Path) -> None:
        self.socket_path = Path(socket_path)

    @property
    def metrics(self) -> HttpMetrics | None:
        return None

    def fetch(self, archive_url: str) -> dict[str, Any]:
        """Fetch one archive URL through the broker.

        Returns a dict shaped like ``FetchResult``: ``status`` is
        ``"ok"``/``"failed"``, ``payload`` is the raw bytes on success, and
        ``error`` carries the failure detail.
        """
        request_id = os.urandom(8).hex()
        request = _json_dumps({"request_id": request_id, "archive_url": archive_url})
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(_READ_TIMEOUT_S)
                sock.connect(str(self.socket_path))
                sock.sendall(_HEADER_STRUCT.pack(len(request)) + request)
                header_raw = _recv_exactly(sock, _HEADER_SIZE)
                (header_len,) = _HEADER_STRUCT.unpack(header_raw)
                header = _json_loads(_recv_exactly(sock, header_len))
                payload_length = int(header.get("payload_length", 0) or 0)
                payload = _recv_exactly(sock, payload_length) if payload_length else b""
        except (OSError, BrokerError) as exc:
            return {
                "status": "failed",
                "error": str(exc) or type(exc).__name__,
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


if __name__ == "__main__":
    from defs.sec_http.broker_cli import main

    raise SystemExit(main())
