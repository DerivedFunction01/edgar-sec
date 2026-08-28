"""Thread-safe request pacing and rate limiting for SEC endpoints."""

from __future__ import annotations

import threading
import time

DEFAULT_RATE_LIMIT_RPS = 4.0
DEFAULT_MIN_INTERVAL_S = 1.0 / DEFAULT_RATE_LIMIT_RPS
MAX_INTERVAL_S = 60.0
THROTTLE_MULTIPLIER = 1.5
RECOVERY_QUIET_S = 30.0
RECOVERY_DECAY = 0.10
RETRY_AFTER_CAP_S = 120.0


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
            if (
                self._interval > self._min_interval
                and now - self._last_throttle > RECOVERY_QUIET_S
            ):
                gap = self._interval - self._min_interval
                self._interval = max(
                    self._min_interval, self._interval - gap * RECOVERY_DECAY
                )
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
                delay = min(
                    max(float(retry_after_s), self._interval),
                    self._max_interval,
                    RETRY_AFTER_CAP_S,
                )
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
                "cool_until_in_s": round(
                    max(0.0, self._cool_until - time.monotonic()), 4
                ),
                "last_throttle_age_s": round(time.monotonic() - self._last_throttle, 4)
                if self._last_throttle
                else None,
            }


__all__ = [
    "DEFAULT_MIN_INTERVAL_S",
    "DEFAULT_RATE_LIMIT_RPS",
    "MAX_INTERVAL_S",
    "RECOVERY_DECAY",
    "RECOVERY_QUIET_S",
    "RETRY_AFTER_CAP_S",
    "THROTTLE_MULTIPLIER",
    "RateLimiter",
]
