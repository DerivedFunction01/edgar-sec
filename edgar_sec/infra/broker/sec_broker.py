"""Managed same-host SEC acquisition broker.

One broker process owns the single production SecHttpClient (rate limiter, cache, failure
ledger), so every live request shares one aggregate pace governed by settings.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

__all__ = [
    "HEALTHCHECK_URL",
    "PROTOCOL_VERSION",
    "BrokerError",
    "BrokerRequestError",
    "StreamedFileResult",
    "bindable_socket_path",
]

#: AF_UNIX addresses are length-capped by the OS (~108 bytes); a socket
#: path at or over this bound cannot be bound or connected at all.
MAX_SOCKET_PATH_CHARS = 100


def bindable_socket_path(socket_path: str | Path) -> Path:
    """Return a bindable form of ``socket_path``, identical when it fits.

    An over-long path remaps deterministically to a short hashed path, so
    bind and connect land on the same address at any root depth.
    """
    path = Path(socket_path)
    if len(str(path)) < MAX_SOCKET_PATH_CHARS:
        return path
    identity = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:24]
    base = Path(tempfile.gettempdir())
    candidate = base / f"edgar-sec-{os.getuid()}" / f"{identity}.sock"
    if len(str(candidate)) >= MAX_SOCKET_PATH_CHARS:
        candidate = Path("/tmp") / f"edgar-sec-{os.getuid()}" / f"{identity}.sock"
    return candidate


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
