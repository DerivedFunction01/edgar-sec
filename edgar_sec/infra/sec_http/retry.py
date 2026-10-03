"""Retry policy, backoff calculation, and default retry limits."""

from __future__ import annotations

import random
from dataclasses import dataclass

from edgar_sec.foundation.runtime.settings.sec import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT_S,
)

from .rate_limit import RETRY_AFTER_CAP_S

BACKOFF_BASE_S = 0.5
BACKOFF_CAP_S = 30.0


@dataclass(slots=True)
class RetryPolicy:
    """Retry classification and exponential jittered backoff computation."""

    max_retries: int = DEFAULT_MAX_RETRIES
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
        return "permanent"

    def delay(self, attempt: int, retry_after_s: float | None = None) -> float:
        """Backoff delay after ``attempt`` (0-based) failed attempts."""
        if retry_after_s is not None:
            base = min(max(float(retry_after_s), 0.0), RETRY_AFTER_CAP_S)
        else:
            base = min(self.backoff_base_s * (2**attempt), self.backoff_cap_s)
        return base * (1.0 + random.uniform(0.0, self.jitter))


__all__ = [
    "BACKOFF_BASE_S",
    "BACKOFF_CAP_S",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_TIMEOUT_S",
    "RetryPolicy",
]
