"""Server side of the SEC acquisition broker: owns the one client."""

from __future__ import annotations

import os
import socket
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.domain.sec_urls import validate_archive_url
from edgar_sec.foundation.hashing import is_sha256_hex_digest
from edgar_sec.foundation.runtime.memory import reclaim
from edgar_sec.infra.broker.sec_broker import (
    HEALTHCHECK_URL,
    BrokerError,
    _HEADER_STRUCT,
    _READ_TIMEOUT_S,
    _RECLAIM_BYTES_THRESHOLD,
    _SOCKET_BACKLOG,
    _STREAM_FAILURE_CODES,
    _json_dumps,
    _json_loads,
    _recv_frame,
)
from edgar_sec.infra.sec_http.client import SecHttpClient
from edgar_sec.infra.sec_http.errors import (
    PermanentHttpError,
    ResponseTooLargeError,
    RetryExhausted,
)
from edgar_sec.infra.sec_http.metrics import HttpMetrics

__all__ = ["SecBroker"]


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
        self._ready = threading.Event()
        self._start_error: BaseException | None = None

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
                "cache_source": None,
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
                    "cache_source": "http_cache",
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
                status_code = getattr(exc, "status_code", None)
                if isinstance(exc, ResponseTooLargeError):
                    error_code = "response_too_large"
                elif isinstance(exc, PermanentHttpError):
                    error_code = (
                        "http_not_found" if status_code == 404 else "http_error"
                    )
                else:
                    error_code = "http_error"
                return {
                    "status": "failed",
                    "error": str(exc) or type(exc).__name__,
                    "error_code": error_code,
                    "status_code": status_code,
                    "payload_length": 0,
                }
            except Exception as exc:  # noqa: BLE001
                return {
                    "status": "failed",
                    "error": str(exc) or type(exc).__name__,
                    "error_code": None,
                    "status_code": None,
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
            "cache_source": "network",
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
            validate_archive_url(url, accession, expected_archive_cik=cik)
            parsed = urlsplit(url)
            path = unquote(parsed.path)
            if (
                not path.startswith(directory)
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
                    not is_sha256_hex_digest(digest)
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
                except (BrokerError, TimeoutError):
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
                        "error_code": result.get("error_code"),
                        "status_code": result.get("status_code"),
                        "payload_length": result["payload_length"],
                        "cache_source": result.get("cache_source"),
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
        try:
            server.bind(str(self.socket_path))
            server.listen(_SOCKET_BACKLOG)
        except BaseException as exc:
            self._start_error = exc
            self._ready.set()
            server.close()
            raise
        server.settimeout(0.5)
        self._server = server
        self._ready.set()
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

    def wait_ready(self, timeout_s: float) -> None:
        """Block until serve() signals the socket is bound and listening.

        A rendezvous, not a poll: scheduling delay cannot fail the wait;
        the timeout guards only a hang, and startup failures re-raise.
        """
        if not self._ready.wait(timeout_s):
            raise RuntimeError(
                f"SecBroker serve thread never signaled readiness on "
                f"{self.socket_path} within {timeout_s}s (hang, not slow start)"
            )
        if self._start_error is not None:
            raise RuntimeError(
                f"SecBroker failed to start on {self.socket_path}"
            ) from self._start_error

    def stop(self) -> None:
        self._stop.set()
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
