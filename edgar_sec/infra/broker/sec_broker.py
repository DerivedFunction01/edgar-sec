"""Managed same-host SEC acquisition broker.

One broker process owns the single production SecHttpClient (rate limiter, cache, failure
ledger), so every live request shares one aggregate pace governed by settings.
"""

from __future__ import annotations

import json
import os
import socket
import struct
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urlsplit

from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.foundation.runtime.memory import reclaim
from edgar_sec.infra.sec_http.client import SecHttpClient
from edgar_sec.infra.sec_http.errors import (
    PermanentHttpError,
    ResponseTooLargeError,
    RetryExhausted,
)
from edgar_sec.infra.sec_http.metrics import HttpMetrics

PROTOCOL_VERSION = 1
_RECLAIM_BYTES_THRESHOLD = 512 * 1024 * 1024
_HEADER_STRUCT = struct.Struct("!I")
_HEADER_SIZE = _HEADER_STRUCT.size
_SOCKET_BACKLOG = 128
_READ_TIMEOUT_S = 30.0
HEALTHCHECK_URL = "healthcheck://broker"


class BrokerError(Exception):
    """Raised when a broker request cannot be satisfied."""


class BrokerRequestError(BrokerError):
    """A broker-reported failure for one archive URL."""


@dataclass(frozen=True, slots=True)
class StreamedFileResult:
    status: Literal["ok", "failed"]
    path: Path | None
    sha256: str | None
    size: int
    requested_url: str
    final_url: str | None
    status_code: int | None
    content_type: str | None
    content_encoding: str | None
    error_code: str | None
    retryable: bool | None


_STREAM_FAILURE_CODES = {
    "http_not_found",
    "http_error",
    "timeout",
    "transport_error",
    "response_too_large",
    "unsafe_redirect",
    "empty_body",
}


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
        staging_root: str | Path | None = None,
    ) -> None:
        self.socket_path = Path(socket_path)
        self._staging_root = Path(staging_root) if staging_root is not None else None
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

    @staticmethod
    def _field(value: Any, name: str, default: Any = None) -> Any:
        if isinstance(value, dict):
            return value.get(name, default)
        return getattr(value, name, default)

    @staticmethod
    def _accession_redirect_validator(
        archive_cik: object, accession_number: object
    ) -> Callable[[str], None]:
        if not isinstance(archive_cik, (str, int)) or isinstance(archive_cik, bool):
            raise ValueError("invalid accession CIK")
        cik = Cik.from_raw(archive_cik)
        if not isinstance(accession_number, str):
            raise ValueError("invalid accession number")
        accession = AccessionNumber.from_any(accession_number)
        directory = f"/Archives/edgar/data/{int(cik)}/{accession.normalized}/"

        def validate(url: str) -> None:
            parsed = urlsplit(url)
            path = unquote(parsed.path)
            if (
                parsed.scheme != "https"
                or parsed.netloc != "www.sec.gov"
                or parsed.query
                or parsed.fragment
                or not path.startswith(directory)
                or not path[len(directory) :]
                or any(part in {".", ".."} for part in path.split("/"))
            ):
                raise ValueError("unsafe redirect outside accession directory")

        return validate

    def _stream_file(self, request: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "operation",
            "request_id",
            "url",
            "max_response_bytes",
            "accession_cik",
            "accession_number",
            "staging_root",
        }
        request_id = request.get("request_id")
        url = request.get("url")

        def failed(
            code: str,
            *,
            retryable: bool = False,
            status_code: int | None = None,
            final_url: str | None = None,
        ) -> dict[str, Any]:
            return {
                "request_id": request_id,
                "status": "failed",
                "path": None,
                "sha256": None,
                "size": 0,
                "requested_url": url if isinstance(url, str) else "",
                "final_url": final_url,
                "status_code": status_code,
                "content_type": None,
                "content_encoding": None,
                "error_code": code,
                "retryable": retryable,
            }

        if set(request) - allowed:
            return failed("invalid_request")
        if (
            not isinstance(request_id, str)
            or not request_id
            or not isinstance(url, str)
        ):
            return failed("invalid_request")
        limit = request.get("max_response_bytes")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            return failed("invalid_request")
        try:
            validate_redirect = self._accession_redirect_validator(
                request.get("accession_cik"), request.get("accession_number")
            )
            validate_redirect(url)
        except (TypeError, ValueError):
            return failed("invalid_scope")

        requested_root = request.get("staging_root")
        if requested_root is None:
            root = self._staging_root or self.socket_path.parent / "sec-broker-staging"
        elif isinstance(requested_root, str) and Path(requested_root).is_absolute():
            root = Path(requested_root)
        else:
            return failed("invalid_path")

        destination: Path | None = None
        keep_destination = False
        with self._semaphore:
            with self._lock:
                self._active += 1
            try:
                root.mkdir(mode=0o700, parents=True, exist_ok=True)
                root = root.resolve(strict=True)
                if not root.is_dir():
                    return failed("invalid_path")
                fd, generated_path = tempfile.mkstemp(
                    prefix="sec-stream-", suffix=".part", dir=root
                )
                os.close(fd)
                destination = Path(generated_path)
                streamed = self._client.stream_to_file(
                    url,
                    destination,
                    max_response_bytes=limit,
                    validate_redirect=validate_redirect,
                )
                code = self._field(streamed, "code")
                if code is not None:
                    failure_code = (
                        code if code in _STREAM_FAILURE_CODES else "transport_error"
                    )
                    result = failed(
                        failure_code,
                        retryable=bool(self._field(streamed, "retryable", False)),
                        status_code=self._field(
                            streamed,
                            "http_status",
                            self._field(streamed, "status_code"),
                        ),
                        final_url=self._field(streamed, "final_url"),
                    )
                    return result

                digest = self._field(streamed, "sha256")
                size = self._field(streamed, "byte_size")
                status_code = self._field(streamed, "status_code")
                final_url = self._field(streamed, "final_url")
                if (
                    not isinstance(digest, str)
                    or len(digest) != 64
                    or any(char not in "0123456789abcdef" for char in digest)
                    or not isinstance(size, int)
                    or isinstance(size, bool)
                    or size <= 0
                    or size > limit
                    or not destination.is_file()
                    or destination.stat().st_size != size
                    or not isinstance(status_code, int)
                    or isinstance(status_code, bool)
                    or not isinstance(final_url, str)
                ):
                    return failed("transport_error")
                validate_redirect(final_url)
                keep_destination = True
                return {
                    "request_id": request_id,
                    "status": "ok",
                    "path": str(destination),
                    "sha256": digest,
                    "size": size,
                    "requested_url": url,
                    "final_url": final_url,
                    "status_code": status_code,
                    "content_type": self._field(streamed, "content_type"),
                    "content_encoding": self._field(streamed, "content_encoding"),
                    "error_code": None,
                    "retryable": None,
                }
            except (PermanentHttpError, ResponseTooLargeError, RetryExhausted) as exc:
                status_code = getattr(exc, "status_code", None)
                if isinstance(exc, ResponseTooLargeError):
                    code = "response_too_large"
                elif isinstance(exc, PermanentHttpError):
                    code = "http_not_found" if status_code == 404 else "http_error"
                else:
                    code = "http_error"
                return failed(
                    code,
                    retryable=isinstance(exc, RetryExhausted),
                    status_code=status_code,
                )
            except ValueError:
                return failed("unsafe_redirect")
            except Exception:  # noqa: BLE001
                return failed("transport_error", retryable=True)
            finally:
                if destination is not None and not keep_destination:
                    try:
                        destination.unlink(missing_ok=True)
                    except OSError:
                        pass
                with self._lock:
                    self._active -= 1

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
                if request.get("operation") == "stream_to_file":
                    response = self._stream_file(request)
                    header = _json_dumps(response)
                    try:
                        conn.sendall(_HEADER_STRUCT.pack(len(header)) + header)
                    except OSError:
                        return
                    continue
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

    def stream_to_file(
        self,
        url: str,
        *,
        max_response_bytes: int,
        accession_cik: str | int,
        accession_number: str,
        staging_root: str | Path | None = None,
    ) -> StreamedFileResult:
        request_id = os.urandom(8).hex()
        request_values: dict[str, Any] = {
            "operation": "stream_to_file",
            "request_id": request_id,
            "url": url,
            "max_response_bytes": max_response_bytes,
            "accession_cik": accession_cik,
            "accession_number": accession_number,
        }
        if staging_root is not None:
            request_values["staging_root"] = str(staging_root)
        request = _json_dumps(request_values)
        header: dict[str, Any] | None = None
        for attempt in (1, 2):
            try:
                header, payload = self._exchange(request)
                if payload:
                    raise BrokerError("stream response unexpectedly contained a body")
                break
            except (OSError, BrokerError):
                self._reset_socket()
                if attempt == 2:
                    return StreamedFileResult(
                        "failed",
                        None,
                        None,
                        0,
                        url,
                        None,
                        None,
                        None,
                        None,
                        "transport_error",
                        True,
                    )
        if header is None or header.get("request_id") != request_id:
            return StreamedFileResult(
                "failed",
                None,
                None,
                0,
                url,
                None,
                None,
                None,
                None,
                "transport_error",
                True,
            )
        path_value = header.get("path")
        return StreamedFileResult(
            "ok" if header.get("status") == "ok" else "failed",
            Path(path_value) if isinstance(path_value, str) else None,
            header.get("sha256") if isinstance(header.get("sha256"), str) else None,
            header.get("size") if isinstance(header.get("size"), int) else 0,
            header.get("requested_url")
            if isinstance(header.get("requested_url"), str)
            else url,
            header.get("final_url")
            if isinstance(header.get("final_url"), str)
            else None,
            header.get("status_code")
            if isinstance(header.get("status_code"), int)
            else None,
            header.get("content_type")
            if isinstance(header.get("content_type"), str)
            else None,
            header.get("content_encoding")
            if isinstance(header.get("content_encoding"), str)
            else None,
            header.get("error_code")
            if isinstance(header.get("error_code"), str)
            else None,
            header.get("retryable")
            if isinstance(header.get("retryable"), bool)
            else None,
        )


__all__ = [
    "HEALTHCHECK_URL",
    "PROTOCOL_VERSION",
    "BrokerError",
    "BrokerRequestError",
    "SecBroker",
    "SecBrokerClient",
    "StreamedFileResult",
]
