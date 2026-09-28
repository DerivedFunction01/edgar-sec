"""Core HTTP client session, rate pacing, disk caching, and failure ledger."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from edgar_sec.foundation.hashing import sha256_bytes
from edgar_sec.foundation.runtime.settings.paths import DEFAULT_CACHE_JSON_TTL_S
from edgar_sec.foundation.runtime.settings.sec import (
    DEFAULT_MAX_FAILURE_ATTEMPTS,
    DEFAULT_MAX_RETRIES,
    DEFAULT_RATE_LIMIT_RPS,
    DEFAULT_TIMEOUT_S,
    DEFAULT_USER_AGENT,
    SecSettings,
)

from .cache import make_cache_store
from .errors import PermanentHttpError, ResponseTooLargeError, RetryExhausted
from .metrics import HttpMetrics
from .rate_limit import RateLimiter
from .retry import RetryPolicy


def default_headers(user_agent: str = DEFAULT_USER_AGENT) -> dict[str, str]:
    """Shared headers for SEC requests."""
    if not user_agent or "@" not in user_agent:
        raise ValueError(
            "user_agent must be formatted as 'AppName/1.0 contact@example.com' or 'Company Admin@domain.com'"
        )
    return {
        "User-Agent": user_agent.strip(),
        "Accept-Encoding": "gzip, deflate",
    }


class SecHttpClient:
    """Production thread-safe SEC HTTP client with pacing, caching, and retries."""

    def __init__(
        self,
        user_agent: str = DEFAULT_USER_AGENT,
        *,
        rate_limiter: RateLimiter | None = None,
        retry_policy: RetryPolicy | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        cache_dir: str | Path | None = None,
        json_ttl_s: int = DEFAULT_CACHE_JSON_TTL_S,
        metrics: HttpMetrics | None = None,
        max_failure_attempts: int = DEFAULT_MAX_FAILURE_ATTEMPTS,
        ignore_failure_history: bool = False,
        max_response_bytes: int | None = None,
        session_factory: Callable[[], Any] | None = None,
    ) -> None:
        if not user_agent:
            raise ValueError("user_agent is required for SecHttpClient")
        self.user_agent = user_agent
        self.headers = default_headers(user_agent)
        self.timeout_s = timeout_s
        self.rate_limiter = rate_limiter or RateLimiter(
            min_interval_s=1.0 / DEFAULT_RATE_LIMIT_RPS
        )
        self.retry_policy = retry_policy or RetryPolicy(max_retries=DEFAULT_MAX_RETRIES)
        self.metrics = metrics or HttpMetrics()
        self.cache_dir = Path(cache_dir).resolve() if cache_dir else None
        self._cache = make_cache_store(self.cache_dir, json_ttl_s=json_ttl_s)
        self.max_failure_attempts = max_failure_attempts
        self.ignore_failure_history = ignore_failure_history
        self.max_response_bytes = max_response_bytes

        # Configure session connection pool. A caller-supplied factory lets
        # tests substitute a scripted session while keeping pacing, retry,
        # caching, and failure-ledger behavior under test.
        self._session = session_factory() if session_factory else requests.Session()
        if hasattr(self._session, "mount"):
            adapter = HTTPAdapter(
                pool_connections=16,
                pool_maxsize=16,
                max_retries=Retry(total=0, connect=0, read=0),
            )
            self._session.mount("https://", adapter)
            self._session.mount("http://", adapter)
        self._lock = threading.Lock()

    @classmethod
    def from_settings(
        cls,
        settings: SecSettings,
        *,
        cache_dir: str | Path | None = None,
        json_ttl_s: int = DEFAULT_CACHE_JSON_TTL_S,
        metrics: HttpMetrics | None = None,
    ) -> SecHttpClient:
        """Construct SecHttpClient from resolved SecSettings."""
        limiter = RateLimiter(min_interval_s=1.0 / settings.rate_limit_rps)
        retry_policy = RetryPolicy(max_retries=settings.max_retries)
        return cls(
            user_agent=settings.header_user_agent,
            rate_limiter=limiter,
            retry_policy=retry_policy,
            timeout_s=settings.timeout_seconds,
            cache_dir=cache_dir,
            json_ttl_s=json_ttl_s,
            metrics=metrics,
            max_failure_attempts=settings.max_failure_attempts,
        )

    # ------------------------------------------------------------------ Cache Probes

    def _cache_get(self, url: str) -> bytes | None:
        if self._cache is not None:
            return self._cache.get(url)
        return None

    def _cache_put(
        self, url: str, payload: bytes, sha256: str, byte_size: int, content_kind: str
    ) -> None:
        if self._cache is not None:
            self._cache.put(url, payload, sha256, byte_size, content_kind)

    def peek_cache(self, url: str) -> bytes | None:
        """Read-only cache probe without consuming a rate slot."""
        cached = self._cache_get(url)
        if cached is not None:
            self.metrics.record_cache_hit()
        return cached

    # ---------------------------------------------------------- Failure Ledger

    def load_failure_entry(self, url: str) -> dict[str, object] | None:
        if self._cache is not None:
            return self._cache.load_failure_entry(url)
        return None

    def _preflight_skip(self, url: str) -> PermanentHttpError | None:
        if self.ignore_failure_history or self._cache is None:
            return None
        entry = self._cache.load_failure_entry(url)
        if not entry:
            return None
        failed_runs = int(entry.get("failed_runs", 0))
        if entry.get("permanent"):
            reason = (
                f"permanent failure on a previous run "
                f"({entry.get('last_kind')}: {entry.get('last_detail')})"
            )
        elif self.max_failure_attempts > 0 and failed_runs >= self.max_failure_attempts:
            reason = (
                f"failed {failed_runs} independent run(s), reaching budget "
                f"of {self.max_failure_attempts}: {entry.get('last_detail')}"
            )
        else:
            return None
        return PermanentHttpError(url, reason, entry.get("last_status"))  # type: ignore[arg-type]

    # ------------------------------------------------------------------ Core Fetch

    def _send(self, url: str) -> requests.Response:
        return self._session.get(url, headers=self.headers, timeout=self.timeout_s)

    def get_bytes(
        self,
        url: str,
        content_kind: str = "bytes",
        *,
        force_refresh: bool = False,
    ) -> bytes:
        """Fetch raw bytes with rate limiting, retries, caching, and failure tracking."""
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
                self._cache_put(url, content, sha, len(content), content_kind)
                if self._cache:
                    self._cache.clear_failure(url)
                return content

            # Status handling
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

            # Permanent 4xx error (e.g. 404 Not Found)
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

        The submissions dataset records per-row acquisition provenance, so the
        byte count and digest of the exact response body must survive the
        parse rather than being discarded by it.
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

    # ------------------------------------------------------------------ SEC URL Helpers

    @staticmethod
    def submissions_url(cik: str | int) -> str:
        """Canonical SEC submission metadata JSON URL for a CIK."""
        padded_cik = str(cik).zfill(10)
        return f"https://data.sec.gov/submissions/CIK{padded_cik}.json"

    @staticmethod
    def archives_url(cik: str | int, accession_number: str, document_name: str) -> str:
        """Canonical SEC archive filing document URL."""
        cik_int = int(cik)
        accession_clean = accession_number.replace("-", "")
        return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_clean}/{document_name}"


__all__ = [
    "PermanentHttpError",
    "ResponseTooLargeError",
    "RetryExhausted",
    "SecHttpClient",
    "default_headers",
]
