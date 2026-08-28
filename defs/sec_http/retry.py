"""Retry policy, backoff calculation, and default retry limits."""

from __future__ import annotations

import random
from dataclasses import dataclass

from .rate_limit import RETRY_AFTER_CAP_S

DEFAULT_TIMEOUT_S = 15.0
DEFAULT_MAX_RETRIES = 4
BACKOFF_BASE_S = 0.5
BACKOFF_CAP_S = 30.0


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


__all__ = [
    "BACKOFF_BASE_S",
    "BACKOFF_CAP_S",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_TIMEOUT_S",
    "RetryPolicy",
]
