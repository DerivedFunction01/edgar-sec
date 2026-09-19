"""Shared SEC HTTP layer: pacing, retries, metrics, and caching."""

from __future__ import annotations

from .cache import DEFAULT_JSON_TTL_S, SqlCacheReader, make_cache_reader
from .client import (
    DEFAULT_SEC_MAX_CONCURRENCY,
    DEFAULT_USER_AGENT,
    SecHttpClient,
    SecTransportProfile,
    default_headers,
    make_sec_http_client,
    resolve_sec_transport_profile,
)
from .errors import PermanentHttpError, ResponseTooLargeError, RetryExhausted
from .metrics import HttpMetrics
from .rate_limit import (
    DEFAULT_MIN_INTERVAL_S,
    DEFAULT_RATE_LIMIT_RPS,
    MAX_INTERVAL_S,
    RECOVERY_DECAY,
    RECOVERY_QUIET_S,
    RETRY_AFTER_CAP_S,
    THROTTLE_MULTIPLIER,
    RateLimiter,
)
from .retry import (
    BACKOFF_BASE_S,
    BACKOFF_CAP_S,
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT_S,
    RetryPolicy,
)

__all__ = [
    "BACKOFF_BASE_S",
    "BACKOFF_CAP_S",
    "DEFAULT_JSON_TTL_S",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_MIN_INTERVAL_S",
    "DEFAULT_RATE_LIMIT_RPS",
    "DEFAULT_SEC_MAX_CONCURRENCY",
    "DEFAULT_TIMEOUT_S",
    "DEFAULT_USER_AGENT",
    "MAX_INTERVAL_S",
    "RECOVERY_DECAY",
    "RECOVERY_QUIET_S",
    "RETRY_AFTER_CAP_S",
    "THROTTLE_MULTIPLIER",
    "HttpMetrics",
    "PermanentHttpError",
    "RateLimiter",
    "ResponseTooLargeError",
    "RetryExhausted",
    "RetryPolicy",
    "SecHttpClient",
    "SecTransportProfile",
    "SqlCacheReader",
    "default_headers",
    "make_cache_reader",
    "make_sec_http_client",
    "resolve_sec_transport_profile",
]
