"""Buffered fetch: whole-body reads, retry handling, and payload decoding."""

from __future__ import annotations

import json
import time
from typing import Any

import requests

from edgar_sec.foundation.hashing import sha256_bytes

from .errors import PermanentHttpError, ResponseTooLargeError, RetryExhausted


class BufferedFetchMixin:
    """Buffered (whole-body) fetch path and decoded payload accessors."""

    def get_bytes(
        self,
        url: str,
        content_kind: str = "bytes",
        *,
        force_refresh: bool = False,
        mutable: bool = False,
    ) -> bytes:
        """Fetch raw bytes with rate limiting, retries, caching, and failure tracking.

        ``mutable`` applies the TTL to a payload that changes despite an archive path.
        """
        if not force_refresh:
            cached = self._cache_get(url)
            if cached is not None:
                self.metrics.record_cache_hit()
                return cached

        skip = self._preflight_skip(url)
        if skip is not None:
            self.metrics.record_failure("ledger_skip", str(skip))
            raise skip

        policy = self.retry_policy

        for attempt in range(policy.max_retries + 1):
            delay = self.rate_limiter.acquire()
            if delay > 0:
                time.sleep(delay)

            send_started = time.monotonic()
            self.metrics.record_attempt()
            try:
                response = self._send(url)
            except requests.exceptions.Timeout as exc:
                self.metrics.record_failure("network", f"timeout: {url}")
                self.rate_limiter.signal_network_error()
                if attempt < policy.max_retries:
                    self.metrics.record_retry()
                    time.sleep(policy.delay(attempt))
                    continue
                if self._cache:
                    self._cache.record_failure(
                        url,
                        kind="timeout",
                        detail=str(exc),
                        status_code=None,
                        permanent=False,
                    )
                raise RetryExhausted(
                    url, f"timeout after {attempt + 1} attempts"
                ) from exc
            except requests.exceptions.RequestException as exc:
                self.metrics.record_failure("network", f"connection_error: {url}")
                self.rate_limiter.signal_network_error()
                if attempt < policy.max_retries:
                    self.metrics.record_retry()
                    time.sleep(policy.delay(attempt))
                    continue
                if self._cache:
                    self._cache.record_failure(
                        url,
                        kind="network",
                        detail=str(exc),
                        status_code=None,
                        permanent=False,
                    )
                raise RetryExhausted(url, f"network error: {exc}") from exc

            content = response.content or b""
            latency = time.monotonic() - send_started
            self.metrics.record_status(response.status_code, latency, len(content))

            if response.status_code == 200:
                if (
                    self.max_response_bytes is not None
                    and len(content) > self.max_response_bytes
                ):
                    if self._cache:
                        self._cache.record_failure(
                            url,
                            kind="size_exceeded",
                            detail=f"response size {len(content)} > {self.max_response_bytes}",
                            status_code=200,
                            permanent=True,
                        )
                    raise ResponseTooLargeError(
                        url, f"response exceeded {self.max_response_bytes} bytes", 200
                    )
                sha = sha256_bytes(content)
                self._cache_put(
                    url, content, sha, len(content), content_kind, mutable=mutable
                )
                if self._cache:
                    self._cache.clear_failure(url)
                return content

            status_kind = policy.classify(response.status_code)
            if status_kind == "throttle":
                retry_after_hdr = response.headers.get("Retry-After")
                retry_after = (
                    float(retry_after_hdr)
                    if retry_after_hdr and retry_after_hdr.isdigit()
                    else None
                )
                self.metrics.record_failure("throttle", f"429 throttled: {url}")
                self.rate_limiter.signal_throttle(retry_after)
                if attempt < policy.max_retries:
                    self.metrics.record_retry()
                    time.sleep(policy.delay(attempt, retry_after))
                    continue
                if self._cache:
                    self._cache.record_failure(
                        url,
                        kind="throttle",
                        detail="HTTP 429 rate limit exceeded",
                        status_code=429,
                        permanent=False,
                    )
                raise RetryExhausted(url, "rate limit 429 retries exhausted", 429)

            if status_kind == "retry":
                self.metrics.record_failure(
                    "http_retry",
                    f"HTTP {response.status_code}: {url}",
                    response.status_code,
                )
                if attempt < policy.max_retries:
                    self.metrics.record_retry()
                    time.sleep(policy.delay(attempt))
                    continue
                if self._cache:
                    self._cache.record_failure(
                        url,
                        kind="retryable_http",
                        detail=f"HTTP {response.status_code}",
                        status_code=response.status_code,
                        permanent=False,
                    )
                raise RetryExhausted(
                    url,
                    f"server error {response.status_code}",
                    response.status_code,
                )

            if self._cache:
                self._cache.record_failure(
                    url,
                    kind="permanent",
                    detail=f"HTTP {response.status_code}",
                    status_code=response.status_code,
                    permanent=True,
                )
            raise PermanentHttpError(
                url, f"HTTP {response.status_code}", response.status_code
            )

        raise RetryExhausted(url, "exhausted all retry attempts")

    def get_text(self, url: str, *, force_refresh: bool = False) -> str:
        """Fetch and decode response as a UTF-8 text string."""
        raw = self.get_bytes(url, content_kind="text", force_refresh=force_refresh)
        return raw.decode("utf-8", errors="replace")

    def get_json(self, url: str, *, force_refresh: bool = False) -> dict[str, Any]:
        """Fetch and parse JSON response payload."""
        text = self.get_text(url, force_refresh=force_refresh)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            if self._cache:
                self._cache.record_failure(
                    url,
                    kind="bad_json",
                    detail=f"malformed JSON: {exc}",
                    status_code=200,
                    permanent=True,
                )
            raise PermanentHttpError(url, f"invalid JSON response: {exc}") from exc
        if not isinstance(parsed, dict):
            raise PermanentHttpError(url, "expected JSON object at root")
        return parsed

    def get_json_ex(
        self, url: str, *, force_refresh: bool = False
    ) -> tuple[dict[str, Any], int, str]:
        """Like :meth:`get_json` but also returns ``(payload, byte_count, response_sha256)``.

        The body's size and digest must survive the parse, for per-row provenance.
        """
        raw = self.get_bytes(url, content_kind="json", force_refresh=force_refresh)
        try:
            parsed = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            if self._cache:
                self._cache.record_failure(
                    url,
                    kind="bad_json",
                    detail=f"malformed JSON: {exc}",
                    status_code=200,
                    permanent=True,
                )
            raise PermanentHttpError(url, f"invalid JSON response: {exc}") from exc
        if not isinstance(parsed, dict):
            raise PermanentHttpError(url, "expected JSON object at root")
        return parsed, len(raw), sha256_bytes(raw)
