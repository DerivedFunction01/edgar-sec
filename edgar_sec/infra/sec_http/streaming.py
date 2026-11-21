"""Metadata-only results for bounded SEC response streaming."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias


StreamFailureCode: TypeAlias = Literal[
    "http_not_found",
    "http_error",
    "timeout",
    "transport_error",
    "response_too_large",
    "unsafe_redirect",
    "empty_body",
]


@dataclass(frozen=True, slots=True)
class StreamedResponse:
    status_code: int
    requested_url: str
    final_url: str
    sha256: str
    byte_size: int
    content_type: str | None
    content_encoding: str | None
    path: Path


@dataclass(frozen=True, slots=True)
class StreamFailure:
    code: StreamFailureCode
    retryable: bool
    http_status: int | None
    detail: str


StreamResult: TypeAlias = StreamedResponse | StreamFailure


__all__ = ["StreamFailure", "StreamFailureCode", "StreamResult", "StreamedResponse"]
