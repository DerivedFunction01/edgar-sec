"""Core HTTP client session, rate pacing, disk caching, and failure ledger."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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
from .client_cache import CacheLedgerMixin
from .client_fetch import BufferedFetchMixin
from .client_streaming import StreamingFetchMixin
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


class SecHttpClient(CacheLedgerMixin, BufferedFetchMixin, StreamingFetchMixin):
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

    def close(self) -> None:
        closer = getattr(self._session, "close", None)
        if callable(closer):
            closer()

    # ------------------------------------------------------------------ Core Fetch

    def _send(self, url: str) -> requests.Response:
        return self._session.get(url, headers=self.headers, timeout=self.timeout_s)


__all__ = [
    "PermanentHttpError",
    "ResponseTooLargeError",
    "RetryExhausted",
    "SecHttpClient",
    "default_headers",
]
