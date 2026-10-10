"""Core HTTP client session, rate pacing, disk caching, and failure ledger."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from edgar_sec.foundation.hashing import sha256_bytes
from edgar_sec.foundation.runtime.settings.paths import DEFAULT_CACHE_TTL_S
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
from .streaming import (
    StreamFailure,
    StreamFailureCode,
    StreamResult,
    StreamedResponse,
)


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
        ttl_s: int = DEFAULT_CACHE_TTL_S,
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
        self._cache = make_cache_store(self.cache_dir, ttl_s=ttl_s)
        self.max_failure_attempts = max_failure_attempts
        self.ignore_failure_history = ignore_failure_history
        self.max_response_bytes = max_response_bytes

        # A caller-supplied session factory lets a test substitute a scripted session while
        # pacing, retry, caching, and the failure ledger still run.
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
        ttl_s: int = DEFAULT_CACHE_TTL_S,
        metrics: HttpMetrics | None = None,
    ) -> SecHttpClient:
        """Construct SecHttpClient from resolved SecSettings."""
        limiter = RateLimiter(min_interval_s=1.0 / settings.rate_limit_rps)
        retry_policy = RetryPolicy(max_retries=settings.max_retries)
        return cls(
            user_agent=settings.header_user_agent,
            rate_limiter=limiter,
            retry_policy=retry_policy,
            timeout_s=settings.timeout_s,
            cache_dir=cache_dir,
            ttl_s=ttl_s,
            metrics=metrics,
            max_failure_attempts=settings.max_failure_attempts,
        )

    # ------------------------------------------------------------------ Cache Probes

    def _cache_get(self, url: str) -> bytes | None:
        if self._cache is not None:
            return self._cache.get(url)
        return None

    def _cache_put(
        self,
        url: str,
        payload: bytes,
        sha256: str,
        byte_size: int,
        content_kind: str,
        *,
        mutable: bool = False,
    ) -> None:
        if self._cache is not None:
            self._cache.put(
                url, payload, sha256, byte_size, content_kind, mutable=mutable
            )

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
                for chunk in response.iter_content(chunk_size=64 * 1024):
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


__all__ = [
    "PermanentHttpError",
    "ResponseTooLargeError",
    "RetryExhausted",
    "SecHttpClient",
    "default_headers",
]
