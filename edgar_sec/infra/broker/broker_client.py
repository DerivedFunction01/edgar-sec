"""Worker-side client for the SEC acquisition broker."""

from __future__ import annotations

import os
import socket
import threading
from pathlib import Path
from typing import Any

from edgar_sec.infra.broker.sec_broker import (
    BrokerError,
    StreamedFileResult,
    _HEADER_SIZE,
    _HEADER_STRUCT,
    _READ_TIMEOUT_S,
    _json_dumps,
    _json_loads,
    _recv_exactly,
)
from edgar_sec.infra.sec_http.metrics import HttpMetrics

__all__ = ["SecBrokerClient"]


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

    def close(self) -> None:
        self._reset_socket()

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
                "error_code": header.get("error_code"),
                "status_code": header.get("status_code"),
                "payload": None,
            }
        return {
            "status": "ok",
            "error": None,
            "payload": payload,
            "cache_source": header.get("cache_source") or "network",
        }

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
