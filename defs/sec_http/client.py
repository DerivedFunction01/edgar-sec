"""Core HTTP client session, request orchestration, caching, and failure ledger."""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import requests

from .errors import PermanentHttpError, ResponseTooLargeError, RetryExhausted
from .metrics import HttpMetrics
from .rate_limit import DEFAULT_RATE_LIMIT_RPS, RateLimiter
from .retry import DEFAULT_MAX_RETRIES, DEFAULT_TIMEOUT_S, RetryPolicy

DEFAULT_USER_AGENT = "EdgarSec/1.0 contact@example.com"


def default_headers(user_agent: str = DEFAULT_USER_AGENT) -> dict:
    """Shared headers for SEC requests.

    No ``Host`` header is set on purpose: the client serves both
    ``data.sec.gov`` and ``www.sec.gov`` endpoints, and pinning a host breaks
    the other (archive requests returned 404 under a hardcoded
    ``Host: data.sec.gov``). The HTTP library derives Host from each URL.
    """
    if not user_agent or "@" not in user_agent:
        raise ValueError(
            "user_agent must be a stable identity like 'AppName/1.0 contact@example.com'"
        )
    return {
        "User-Agent": user_agent,
        "Accept-Encoding": "gzip, deflate",
    }


@dataclass(frozen=True)
class SecTransportProfile:
    """Consolidated SEC transport settings profile."""

    user_agent: str
    rate_limit_rps: float = DEFAULT_RATE_LIMIT_RPS
    timeout_s: float = DEFAULT_TIMEOUT_S
    max_retries: int = DEFAULT_MAX_RETRIES
    max_failure_attempts: int = 3
    cache_dir: str | None = None
    max_response_bytes: int | None = None
    ignore_failure_history: bool = False


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
        user_agent: str | None = None,
        rate_limiter: RateLimiter | None = None,
        retry_policy: RetryPolicy | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        cache_dir: str | None = None,
        max_response_bytes: int | None = None,
        metrics: HttpMetrics | None = None,
        session_factory: Callable[[], Any] = requests.Session,
        max_failure_attempts: int = 3,
        ignore_failure_history: bool = False,
        profile: SecTransportProfile | None = None,
    ):
        if profile is not None:
            user_agent = user_agent or profile.user_agent
            timeout_s = (
                profile.timeout_s if timeout_s == DEFAULT_TIMEOUT_S else timeout_s
            )
            cache_dir = cache_dir if cache_dir is not None else profile.cache_dir
            max_response_bytes = max_response_bytes or profile.max_response_bytes
            max_failure_attempts = (
                profile.max_failure_attempts
                if max_failure_attempts == 3
                else max_failure_attempts
            )
            ignore_failure_history = (
                ignore_failure_history or profile.ignore_failure_history
            )
            if rate_limiter is None and profile.rate_limit_rps > 0:
                rate_limiter = RateLimiter(min_interval_s=1.0 / profile.rate_limit_rps)
            if retry_policy is None and profile.max_retries >= 0:
                retry_policy = RetryPolicy(max_retries=profile.max_retries)

        if not user_agent:
            raise ValueError(
                "user_agent is required for SecHttpClient (or supply via SecTransportProfile)"
            )
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
                if (
                    self.max_response_bytes is not None
                    and len(content) > self.max_response_bytes
                ):
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
                raise PermanentHttpError(
                    url, f"status {response.status_code}", response.status_code
                )

            last_reason = f"status {response.status_code}"
            last_status = response.status_code
            if kind == "throttle":
                self.metrics.record_failure("throttle", f"status 429: {url}", 429)
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


__all__ = [
    "SecHttpClient",
    "SecTransportProfile",
    "default_headers",
]
