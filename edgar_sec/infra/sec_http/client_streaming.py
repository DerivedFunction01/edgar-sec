"""Streaming fetch: bounded decoded responses written to caller-owned files."""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urljoin

import requests

from edgar_sec.foundation.io import DEFAULT_IO_CHUNK_SIZE

from .streaming import (
    StreamFailure,
    StreamFailureCode,
    StreamResult,
    StreamedResponse,
)


class StreamingFetchMixin:
    """Streaming path: redirect-checked, size-bounded writes to disk."""

    def stream_to_file(
        self,
        url: str,
        destination: str | Path,
        *,
        max_response_bytes: int,
        validate_redirect: Callable[[str], None],
    ) -> StreamResult:
        """Stream a bounded decoded response to a caller-owned destination."""
        if (
            isinstance(max_response_bytes, bool)
            or not isinstance(max_response_bytes, int)
            or max_response_bytes <= 0
        ):
            raise ValueError("max_response_bytes must be a positive finite integer")

        target = Path(destination)

        def failure(
            code: StreamFailureCode,
            detail: str,
            *,
            retryable: bool,
            status_code: int | None = None,
            kind: str,
            permanent: bool,
            metric_kind: str | None = None,
        ) -> StreamFailure:
            self.metrics.record_failure(metric_kind or kind, detail, status_code)
            if self._cache:
                self._cache.record_failure(
                    url,
                    kind=kind,
                    detail=detail,
                    status_code=status_code,
                    permanent=permanent,
                )
            return StreamFailure(code, retryable, status_code, detail)

        skipped = self._preflight_skip(url)
        if skipped is not None:
            return StreamFailure("http_error", False, skipped.status_code, str(skipped))

        policy = self.retry_policy
        for attempt in range(policy.max_retries + 1):
            response = None
            temporary: Path | None = None
            output = None
            current_url = url
            redirect_count = 0
            send_started = time.monotonic()
            try:
                while True:
                    delay = self.rate_limiter.acquire()
                    if delay > 0:
                        time.sleep(delay)
                    self.metrics.record_attempt()
                    response = self._session.get(
                        current_url,
                        headers=self.headers,
                        timeout=self.timeout_s,
                        stream=True,
                        allow_redirects=False,
                    )
                    status = response.status_code
                    response_headers = response.headers
                    location = response_headers.get("Location")
                    if status in (301, 302, 303, 307, 308) and location:
                        self.metrics.record_status(
                            status, time.monotonic() - send_started, 0
                        )
                        redirect_url = urljoin(
                            getattr(response, "url", None) or current_url, location
                        )
                        response.close()
                        response = None
                        try:
                            validate_redirect(redirect_url)
                        except Exception as exc:
                            return failure(
                                "unsafe_redirect",
                                f"redirect rejected: {exc}",
                                retryable=False,
                                status_code=status,
                                kind="unsafe_redirect",
                                permanent=True,
                            )
                        redirect_count += 1
                        if redirect_count >= requests.sessions.DEFAULT_REDIRECT_LIMIT:
                            return failure(
                                "unsafe_redirect",
                                "redirect limit exceeded",
                                retryable=False,
                                status_code=status,
                                kind="unsafe_redirect",
                                permanent=True,
                            )
                        current_url = redirect_url
                        send_started = time.monotonic()
                        continue
                    break

                status = response.status_code
                final_url = getattr(response, "url", None) or current_url
                if status != 200:
                    latency = time.monotonic() - send_started
                    self.metrics.record_status(status, latency, 0)
                    if status == 404:
                        response.close()
                        response = None
                        return failure(
                            "http_not_found",
                            f"HTTP 404: {url}",
                            retryable=False,
                            status_code=404,
                            kind="not_found",
                            permanent=True,
                        )
                    status_kind = policy.classify(status)
                    if status_kind in ("throttle", "retry"):
                        retry_after_header = response_headers.get("Retry-After")
                        try:
                            retry_after = (
                                float(retry_after_header)
                                if retry_after_header
                                else None
                            )
                        except ValueError:
                            retry_after = None
                        response.close()
                        response = None
                        if status_kind == "throttle":
                            self.rate_limiter.signal_throttle(retry_after)
                            kind = "throttle"
                        else:
                            kind = "http_retry"
                        self.metrics.record_failure(
                            kind, f"HTTP {status}: {url}", status
                        )
                        if attempt < policy.max_retries:
                            self.metrics.record_retry()
                            time.sleep(policy.delay(attempt, retry_after))
                            continue
                        return failure(
                            "http_error",
                            f"HTTP {status}: retry budget exhausted",
                            retryable=True,
                            status_code=status,
                            kind="retryable_http",
                            permanent=False,
                        )
                    response.close()
                    response = None
                    return failure(
                        "http_error",
                        f"HTTP {status}: {url}",
                        retryable=False,
                        status_code=status,
                        kind="permanent",
                        permanent=True,
                    )

                length_header = response_headers.get("Content-Length")
                if length_header:
                    try:
                        declared_size = int(length_header)
                    except (TypeError, ValueError):
                        declared_size = 0
                    if declared_size > max_response_bytes:
                        self.metrics.record_status(
                            status, time.monotonic() - send_started, 0
                        )
                        response.close()
                        response = None
                        return failure(
                            "response_too_large",
                            f"declared response size {declared_size} exceeds {max_response_bytes} bytes",
                            retryable=False,
                            status_code=status,
                            kind="size_exceeded",
                            permanent=True,
                        )

                descriptor, temporary_name = tempfile.mkstemp(
                    prefix=".sec-stream-", suffix=".tmp", dir=target.parent
                )
                temporary = Path(temporary_name)
                output = os.fdopen(descriptor, "wb")
                digest = hashlib.sha256()
                byte_size = 0
                too_large = False
                for chunk in response.iter_content(chunk_size=DEFAULT_IO_CHUNK_SIZE):
                    if not chunk:
                        continue
                    byte_size += len(chunk)
                    if byte_size > max_response_bytes:
                        too_large = True
                        break
                    digest.update(chunk)
                    output.write(chunk)
                latency = time.monotonic() - send_started
                self.metrics.record_status(status, latency, byte_size)
                response.close()
                response = None
                if too_large:
                    output.close()
                    output = None
                    temporary.unlink(missing_ok=True)
                    temporary = None
                    return failure(
                        "response_too_large",
                        f"response exceeded {max_response_bytes} bytes",
                        retryable=False,
                        status_code=status,
                        kind="size_exceeded",
                        permanent=True,
                    )
                if byte_size == 0:
                    output.close()
                    output = None
                    temporary.unlink(missing_ok=True)
                    temporary = None
                    return failure(
                        "empty_body",
                        "successful response had an empty body",
                        retryable=False,
                        status_code=status,
                        kind="empty_body",
                        permanent=True,
                    )
                output.flush()
                os.fsync(output.fileno())
                output.close()
                output = None
                content_type = response_headers.get("Content-Type")
                content_encoding = response_headers.get("Content-Encoding")
                os.replace(temporary, target)
                temporary = None
                if self._cache:
                    self._cache.clear_failure(url)
                return StreamedResponse(
                    status_code=status,
                    requested_url=url,
                    final_url=final_url,
                    sha256=digest.hexdigest(),
                    byte_size=byte_size,
                    content_type=content_type,
                    content_encoding=content_encoding,
                    path=target,
                )
            except requests.exceptions.Timeout as exc:
                self.rate_limiter.signal_network_error()
                if attempt < policy.max_retries:
                    self.metrics.record_failure("network", f"timeout: {url}")
                    self.metrics.record_retry()
                    time.sleep(policy.delay(attempt))
                    continue
                return failure(
                    "timeout",
                    str(exc),
                    retryable=True,
                    kind="timeout",
                    permanent=False,
                    metric_kind="network",
                )
            except requests.exceptions.RequestException as exc:
                self.rate_limiter.signal_network_error()
                if attempt < policy.max_retries:
                    self.metrics.record_failure("network", f"connection_error: {url}")
                    self.metrics.record_retry()
                    time.sleep(policy.delay(attempt))
                    continue
                return failure(
                    "transport_error",
                    str(exc),
                    retryable=True,
                    kind="network",
                    permanent=False,
                    metric_kind="network",
                )
            finally:
                if response is not None:
                    response.close()
                if output is not None:
                    output.close()
                if temporary is not None:
                    temporary.unlink(missing_ok=True)

        return failure(
            "transport_error",
            "exhausted all retry attempts",
            retryable=True,
            kind="network",
            permanent=False,
        )
