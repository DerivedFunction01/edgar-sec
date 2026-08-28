"""Thread-safe request and response metrics collector."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


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

    def record_status(
        self, status_code: int, latency_s: float, byte_count: int
    ) -> None:
        with self._lock:
            self.responses_2xx += 1
            self.status_counts[str(status_code)] = (
                self.status_counts.get(str(status_code), 0) + 1
            )
            self.latency_sum_s += latency_s
            self.bytes_received += byte_count

    def record_failure(
        self, kind: str, detail: str, status_code: int | None = None
    ) -> None:
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


__all__ = ["HttpMetrics"]
