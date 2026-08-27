"""Shared SEC HTTP layer: pacing, retries, metrics, and optional caching.

This module is domain neutral: it owns request pacing, headers, retry
classification, response metrics, and optional response caching. Metadata
parsing and webpage parsing must not reimplement these rules.

Design notes carried over from old-webpage.py:

- A process-local thread-safe limiter reserves the next request slot under a
  lock; callers sleep outside the lock so unrelated workers are never blocked
  by a sleeping lock holder.
- HTTP 429 is handled specially: ``Retry-After`` when supplied, an increased
  delay after throttling, and gradual recovery only after a quiet period.
- Timeouts/connection failures are classified separately from rate-limit
  responses; network failures may retry without being treated as proof that
  the request rate is too high.
- Transient 5xx responses retry with jittered backoff; 404 and other
  non-retryable 4xx responses are permanent and never retried.
- Request counters, status counts, latency, bytes, retries, and last-error
  details are collected for run status and diagnostics.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import requests

# Conservative default: SEC's published guidance is at most 10 req/s; stay
# well under it. One process/limiter per machine: if machines share an
# egress IP the configured rate must be lowered or coordination added.
DEFAULT_MIN_INTERVAL_S = 0.25
MAX_INTERVAL_S = 60.0
THROTTLE_MULTIPLIER = 1.5
RECOVERY_QUIET_S = 30.0
RECOVERY_DECAY = 0.10  # fraction of the gap removed per throttle check
BACKOFF_BASE_S = 0.5
BACKOFF_CAP_S = 30.0
RETRY_AFTER_CAP_S = 120.0


class PermanentHttpError(Exception):
    """Non-retryable failure (404, non-retryable 4xx, bad payload)."""

    def __init__(self, url: str, reason: str, status_code: int | None = None):
        self.url = url
        self.reason = reason
        self.status_code = status_code
        super().__init__(f"permanent error for {url}: {reason} (status={status_code})")


class RetryExhausted(Exception):
    """Retry budget exhausted for a transient failure."""

    def __init__(self, url: str, reason: str, status_code: int | None = None):
        self.url = url
        self.reason = reason
        self.status_code = status_code
        super().__init__(f"retries exhausted for {url}: {reason} (status={status_code})")


class ResponseTooLargeError(PermanentHttpError):
    """Response exceeded the configured size limit."""


class RateLimiter:
    """Thread-safe limiter that reserves the next request slot.

    ``acquire()`` reserves the next slot under a lock and returns how long
    the caller must sleep before sending. Sleeping happens outside the lock.
    """

    def __init__(
        self,
        min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
        max_interval_s: float = MAX_INTERVAL_S,
    ):
        if min_interval_s <= 0:
            raise ValueError("min_interval_s must be positive")
        self._min_interval = float(min_interval_s)
        self._max_interval = float(max_interval_s)
        self._interval = float(min_interval_s)
        self._next_slot = time.monotonic()
        self._cool_until = 0.0
        self._last_throttle = 0.0
        self._lock = threading.Lock()

    @property
    def interval(self) -> float:
        with self._lock:
            return self._interval

    def acquire(self) -> float:
        """Reserve the next request slot; return the delay before sending."""
        with self._lock:
            now = time.monotonic()
            # Gradual recovery: only after a quiet period without throttling.
            if self._interval > self._min_interval and now - self._last_throttle > RECOVERY_QUIET_S:
                gap = self._interval - self._min_interval
                self._interval = max(self._min_interval, self._interval - gap * RECOVERY_DECAY)
            wake = max(self._next_slot, now, self._cool_until)
            self._next_slot = wake + self._interval
            return max(0.0, wake - now)

    def signal_throttle(self, retry_after_s: float | None = None) -> float:
        """Record a rate-limit response and raise the delay.

        Never sleeps while holding the lock.
        """
        with self._lock:
            now = time.monotonic()
            self._last_throttle = now
            if retry_after_s is not None:
                delay = min(max(float(retry_after_s), self._interval), self._max_interval, RETRY_AFTER_CAP_S)
            else:
                delay = min(self._interval * THROTTLE_MULTIPLIER, self._max_interval)
            self._interval = max(self._interval, delay)
            self._cool_until = now + delay
            return delay

    def signal_network_error(self) -> None:
        """Record a network failure without treating it as a rate signal."""

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "current_interval_s": round(self._interval, 4),
                "cool_until_in_s": round(max(0.0, self._cool_until - time.monotonic()), 4),
                "last_throttle_age_s": round(time.monotonic() - self._last_throttle, 4)
                if self._last_throttle
                else None,
            }


@dataclass
class RetryPolicy:
    """Retry classification and backoff computation."""

    max_retries: int = 4
    backoff_base_s: float = BACKOFF_BASE_S
    backoff_cap_s: float = BACKOFF_CAP_S
    jitter: float = 0.25

    def classify(self, status_code: int) -> str:
        """Classify an HTTP status: 'ok', 'throttle', 'retry', or 'permanent'."""
        if status_code == 200:
            return "ok"
        if status_code == 429:
            return "throttle"
        if status_code in (408, 425):
            return "retry"
        if 500 <= status_code < 600:
            return "retry"
        # 404 and all other 4xx are permanent.
        return "permanent"

    def delay(self, attempt: int, retry_after_s: float | None = None) -> float:
        """Backoff delay after ``attempt`` (0-based) failed attempts."""
        if retry_after_s is not None:
            base = min(max(float(retry_after_s), 0.0), RETRY_AFTER_CAP_S)
        else:
            base = min(self.backoff_base_s * (2**attempt), self.backoff_cap_s)
        return base * (1.0 + random.uniform(0.0, self.jitter))


@dataclass
class HttpMetrics:
    """Thread-safe request/response counters for run status and diagnostics."""

    requests_total: int = 0
    cache_hits: int = 0
    responses_2xx: int = 0
    status_counts: dict = field(default_factory=dict)
    throttled_count: int = 0
    network_errors: int = 0
    retries_used: int = 0
    bytes_received: int = 0
    latency_sum_s: float = 0.0
    last_error: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_attempt(self) -> None:
        """Count one actual HTTP send attempt (including network failures)."""
        with self._lock:
            self.requests_total += 1

    def record_status(self, status_code: int, latency_s: float, byte_count: int) -> None:
        with self._lock:
            self.responses_2xx += 1
            self.status_counts[str(status_code)] = self.status_counts.get(str(status_code), 0) + 1
            self.latency_sum_s += latency_s
            self.bytes_received += byte_count

    def record_failure(self, kind: str, detail: str, status_code: int | None = None) -> None:
        """Record a failure kind; HTTP status counts are kept by
        record_status, so no status is double-counted here."""
        with self._lock:
            if kind == "throttle":
                self.throttled_count += 1
            elif kind == "network":
                self.network_errors += 1
            self.last_error = detail

    def record_retry(self) -> None:
        with self._lock:
            self.retries_used += 1

    def record_cache_hit(self) -> None:
        with self._lock:
            self.cache_hits += 1

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "requests_total": self.requests_total,
                "cache_hits": self.cache_hits,
                "responses_2xx": self.responses_2xx,
                "status_counts": dict(self.status_counts),
                "throttled_count": self.throttled_count,
                "network_errors": self.network_errors,
                "retries_used": self.retries_used,
                "bytes_received": self.bytes_received,
                "latency_sum_s": round(self.latency_sum_s, 4),
                "last_error": self.last_error,
            }


def default_headers(user_agent: str) -> dict:
    if not user_agent or "@" not in user_agent:
        raise ValueError(
            "user_agent must be a stable identity like 'AppName/1.0 contact@example.com'"
        )
    return {
        "User-Agent": user_agent,
        "Accept-Encoding": "gzip, deflate",
        "Host": "data.sec.gov",
    }


class SecHttpClient:
    """Single request path for JSON and text responses.

    Pacing is applied exactly once per actual HTTP request, inside this
    class, never in the caller. A session may be injected for tests.

    When ``cache_dir`` is set, a persistent failure ledger records URLs
    whose retry budget was exhausted. Transient failures accumulate
    ``failed_runs`` (one increment per independently failed run/session);
    once ``failed_runs`` reaches ``max_failure_attempts`` — or the failure
    was classified permanent (404, bad payload) — the URL is skipped
    without any HTTP request. Successful responses clear their ledger
    entry, so an empty/transiently broken URL recovered elsewhere can be
    retried again here. Pass ``ignore_failure_history=True`` to force
    attempts regardless of history.
    """

    def __init__(
        self,
        user_agent: str,
        rate_limiter: RateLimiter | None = None,
        retry_policy: RetryPolicy | None = None,
        timeout_s: float = 15.0,
        cache_dir: str | None = None,
        max_response_bytes: int | None = None,
        metrics: HttpMetrics | None = None,
        session_factory: Callable[[], Any] = requests.Session,
        max_failure_attempts: int = 3,
        ignore_failure_history: bool = False,
    ):
        self.rate_limiter = rate_limiter or RateLimiter()
        self.retry_policy = retry_policy or RetryPolicy()
        self.timeout_s = timeout_s
        self.cache_dir = cache_dir
        self.max_response_bytes = max_response_bytes
        self.metrics = metrics or HttpMetrics()
        self.headers = default_headers(user_agent)
        self.max_failure_attempts = max_failure_attempts
        self.ignore_failure_history = ignore_failure_history
        self._session = session_factory()

    # ------------------------------------------------------------------ cache

    def _cache_path(self, url: str) -> str | None:
        if not self.cache_dir:
            return None
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return os.path.join(self.cache_dir, digest + ".cache")

    def _cache_get(self, url: str) -> bytes | None:
        path = self._cache_path(url)
        if path and os.path.exists(path):
            with open(path, "rb") as fh:
                return fh.read()
        return None

    def _cache_put(self, url: str, payload: bytes) -> None:
        path = self._cache_path(url)
        if not path:
            return
        os.makedirs(self.cache_dir, exist_ok=True)  # type: ignore[type-var]
        tmp = path + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(payload)
        os.replace(tmp, path)

    # ---------------------------------------------------------- failure ledger

    def _failure_path(self, url: str) -> str | None:
        if not self.cache_dir:
            return None
        digest = hashlib.sha256(("failure:" + url).encode("utf-8")).hexdigest()
        return os.path.join(self.cache_dir, "failures", digest + ".json")

    def load_failure_entry(self, url: str) -> dict | None:
        path = self._failure_path(url)
        if not path or not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    def _record_failure(
        self,
        url: str,
        *,
        kind: str,
        detail: str,
        status_code: int | None = None,
        permanent: bool = False,
    ) -> dict | None:
        """Persist one failed independent run for this URL. Atomic rename."""
        path = self._failure_path(url)
        if not path:
            return None
        previous = self.load_failure_entry(url) or {}
        entry = {
            "url": url,
            "failed_runs": int(previous.get("failed_runs", 0)) + 1,
            "last_kind": kind,
            "last_status": status_code,
            "last_detail": detail[:500],
            "permanent": bool(permanent or previous.get("permanent")),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(entry, fh, sort_keys=True)
        os.replace(tmp, path)
        return entry

    def _clear_failure(self, url: str) -> None:
        path = self._failure_path(url)
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:  # pragma: no cover
                pass

    def _preflight_skip(self, url: str) -> PermanentHttpError | None:
        """Return an error when history proves this URL should be skipped."""
        if self.ignore_failure_history:
            return None
        entry = self.load_failure_entry(url)
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
                f"failed {failed_runs} independent run(s), reaching the "
                f"budget of {self.max_failure_attempts}: {entry.get('last_detail')}"
            )
        else:
            return None
        return PermanentHttpError(url, reason, entry.get("last_status"))

    # ----------------------------------------------------------------- plumbing

    def _send(self, url: str) -> requests.Response:
        return self._session.get(url, headers=self.headers, timeout=self.timeout_s)

    def _fetch(self, url: str) -> bytes:
        cached = self._cache_get(url)
        if cached is not None:
            self.metrics.record_cache_hit()
            return cached

        # Failure-ledger preflight: skip without any request when history
        # proves the URL is permanently broken or exhausted its budget.
        skip = self._preflight_skip(url)
        if skip is not None:
            self.metrics.record_failure("ledger_skip", str(skip))
            raise skip

        policy = self.retry_policy
        last_reason = "unknown"
        last_status: int | None = None

        def exhaust(kind: str, reason: str, status: int | None, cause=None):
            # One ledger increment per independently failed run.
            self._record_failure(
                url,
                kind=kind,
                detail=reason,
                status_code=status,
                permanent=(kind == "permanent"),
            )
            if kind == "permanent":
                raise PermanentHttpError(url, reason, status) from cause
            raise RetryExhausted(url, reason, status) from cause

        for attempt in range(policy.max_retries + 1):
            delay = self.rate_limiter.acquire()
            if delay > 0:
                time.sleep(delay)

            send_started = time.monotonic()
            self.metrics.record_attempt()
            try:
                response = self._send(url)
            except requests.exceptions.Timeout as exc:
                last_reason, last_status = "timeout", None
                self.metrics.record_failure("network", f"timeout: {url}")
                self.rate_limiter.signal_network_error()
                if attempt < policy.max_retries:
                    self.metrics.record_retry()
                    time.sleep(policy.delay(attempt))
                    continue
                exhaust("transient_network", last_reason, last_status, exc)  # type: ignore[misc]
            except requests.exceptions.ConnectionError as exc:
                last_reason, last_status = "connection_error", None
                self.metrics.record_failure("network", f"connection_error: {url}")
                self.rate_limiter.signal_network_error()
                if attempt < policy.max_retries:
                    self.metrics.record_retry()
                    time.sleep(policy.delay(attempt))
                    continue
                exhaust("transient_network", last_reason, last_status, exc)

            content = response.content or b""
            latency = time.monotonic() - send_started
            self.metrics.record_status(response.status_code, latency, len(content))

            if response.status_code == 200:
                if self.max_response_bytes is not None and len(content) > self.max_response_bytes:
                    self._record_failure(
                        url,
                        kind="response_too_large",
                        detail=f"response size {len(content)} exceeds limit {self.max_response_bytes}",
                        status_code=200,
                        permanent=True,
                    )
                    raise ResponseTooLargeError(
                        url,
                        f"response size {len(content)} exceeds limit {self.max_response_bytes}",
                        200,
                    )
                self._cache_put(url, content)
                self._clear_failure(url)
                return content

            kind = policy.classify(response.status_code)
            retry_after = self._parse_retry_after(response)

            if kind == "permanent":
                self.metrics.record_failure(
                    "permanent",
                    f"status {response.status_code}: {url}",
                    response.status_code,
                )
                self._record_failure(
                    url,
                    kind="permanent",
                    detail=f"status {response.status_code}",
                    status_code=response.status_code,
                    permanent=True,
                )
                raise PermanentHttpError(url, f"status {response.status_code}", response.status_code)

            last_reason = f"status {response.status_code}"
            last_status = response.status_code
            if kind == "throttle":
                self.metrics.record_failure(
                    "throttle", f"status 429: {url}", 429
                )
                self.rate_limiter.signal_throttle(retry_after)

            if attempt < policy.max_retries:
                self.metrics.record_retry()
                if kind != "throttle":
                    # For throttling the limiter already enforces the wait
                    # (Retry-After / increased interval); do not double-sleep.
                    time.sleep(policy.delay(attempt))
                continue

        exhaust("transient_exhausted", last_reason, last_status)

    @staticmethod
    def _parse_retry_after(response: requests.Response) -> float | None:
        raw = response.headers.get("Retry-After") if response.headers else None
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    # -------------------------------------------------------------------- API

    def _decode_failure(self, url: str, exc: Exception) -> PermanentHttpError:
        """A 200 whose body is empty/unparseable is recorded as a permanent
        content failure so later sessions skip it like any 404."""
        self._record_failure(
            url,
            kind="bad_payload",
            detail=str(exc),
            status_code=200,
            permanent=True,
        )
        return PermanentHttpError(url, str(exc), 200)

    def get_text(self, url: str) -> str:
        payload = self._fetch(url)
        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise self._decode_failure(url, exc) from exc

    def get_json(self, url: str) -> Any:
        payload = self._fetch(url)
        try:
            parsed = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise self._decode_failure(url, exc) from exc
        self._clear_failure(url)
        return parsed

    def get_json_ex(self, url: str) -> tuple[Any, int, str]:
        """Like get_json but also returns (byte_count, response_sha256)."""
        payload = self._fetch(url)
        try:
            parsed = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise self._decode_failure(url, exc) from exc
        return parsed, len(payload), hashlib.sha256(payload).hexdigest()
