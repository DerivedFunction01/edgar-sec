from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import cast

from edgar_sec.domain.sec_urls import parse_archive_url
from edgar_sec.foundation.hashing import is_sha256_hex_digest
from edgar_sec.foundation.runtime.settings import (
    resolve_runtime_settings,
    resolve_settings,
)
from edgar_sec.foundation.runtime.settings.validators import positive_int_type
from edgar_sec.infra.broker.daemon import managed_broker
from edgar_sec.infra.broker.sec_broker import SecBrokerClient
from edgar_sec.infra.sec_http.client import SecHttpClient
from edgar_sec.infra.sec_http.streaming import (
    StreamFailure,
    StreamFailureCode,
    StreamResult,
    StreamedResponse,
)


class _LazySecTransport:
    def __init__(self, factory: Callable[[], SecHttpClient]) -> None:
        self._factory = factory
        self._http_client: SecHttpClient | None = None
        self._socket_directory: tempfile.TemporaryDirectory[str] | None = None
        self._broker_context: AbstractContextManager[SecBrokerClient] | None = None
        self._broker: SecBrokerClient | None = None

    def _start_broker(self) -> SecBrokerClient:
        if self._broker is not None:
            return self._broker
        self._http_client = self._factory()
        try:
            self._socket_directory = tempfile.TemporaryDirectory(
                prefix="edgar-sec-broker-"
            )
            socket_path = Path(self._socket_directory.name) / "broker.sock"
            context = managed_broker(socket_path, http_client=self._http_client)
            broker = context.__enter__()
        except Exception:
            try:
                self._http_client.close()
            finally:
                self._http_client = None
                if self._socket_directory is not None:
                    self._socket_directory.cleanup()
                    self._socket_directory = None
            raise
        self._broker_context = context
        self._broker = broker
        return broker

    def stream_to_file(
        self,
        url: str,
        destination: str | Path,
        *,
        max_response_bytes: int,
        validate_redirect: Callable[[str], None],
    ) -> StreamResult:
        archive = parse_archive_url(url)
        if archive is None:
            return StreamFailure("unsafe_redirect", False, None, "invalid archive URL")
        try:
            result = self._start_broker().stream_to_file(
                url,
                max_response_bytes=max_response_bytes,
                accession_cik=archive.archive_cik,
                accession_number=archive.accession,
                staging_root=Path(destination).parent,
            )
        except (OSError, RuntimeError) as error:
            return StreamFailure("transport_error", True, None, str(error))
        if result.status != "ok":
            code = cast(StreamFailureCode, result.error_code or "transport_error")
            return StreamFailure(
                code,
                bool(result.retryable),
                result.status_code,
                result.error_code or "SEC broker stream failed",
            )
        source = result.path
        if (
            source is None
            or result.sha256 is None
            or result.final_url is None
            or result.status_code is None
            or result.requested_url != url
            or result.size < 1
            or result.size > max_response_bytes
            or not is_sha256_hex_digest(result.sha256)
            or source.is_symlink()
            or not source.is_file()
            or source.stat().st_size != result.size
            or not source.resolve().is_relative_to(Path(destination).parent.resolve())
        ):
            return StreamFailure(
                "transport_error",
                False,
                result.status_code,
                "invalid broker stream result",
            )
        validate_redirect(result.final_url)
        os.replace(source, destination)
        return StreamedResponse(
            status_code=result.status_code,
            requested_url=result.requested_url,
            final_url=result.final_url,
            sha256=result.sha256,
            byte_size=result.size,
            content_type=result.content_type,
            content_encoding=result.content_encoding,
            path=Path(destination),
        )

    def close(self) -> None:
        try:
            if self._broker is not None:
                self._broker.close()
        finally:
            try:
                if self._broker_context is not None:
                    self._broker_context.__exit__(None, None, None)
            finally:
                try:
                    if self._http_client is not None:
                        self._http_client.close()
                finally:
                    if self._socket_directory is not None:
                        self._socket_directory.cleanup()


def response_byte_limit(value: int | None) -> int:
    if value is not None:
        return positive_int_type(str(value))
    settings = resolve_settings(include=("acquisition",))
    return positive_int_type(str(settings["acquisition.max_response_bytes"]))


def sec_transport_factory() -> SecHttpClient:
    settings = resolve_runtime_settings()
    return SecHttpClient.from_settings(
        settings.sec,
        cache_dir=settings.cache_root,
        ttl_s=settings.ttl_s,
    )
