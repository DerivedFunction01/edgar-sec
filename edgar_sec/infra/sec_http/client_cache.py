"""Cache probes, failure-ledger preflight, and cache administration."""

from __future__ import annotations

from .errors import PermanentHttpError


class CacheLedgerMixin:
    """Cache and failure-ledger surface, delegated to the cache store."""

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

    def clear_cache(
        self,
        *,
        url: str | None = None,
        url_pattern: str | None = None,
        cik: str | int | None = None,
        kind: str | None = None,
        older_than_s: int | float | None = None,
        expired_only: bool = False,
        clear_failures: bool = False,
        vacuum: bool = True,
    ) -> int:
        """Clear matching entries from the response cache."""
        if self._cache is not None:
            return self._cache.clear(
                url=url,
                url_pattern=url_pattern,
                cik=cik,
                kind=kind,
                older_than_s=older_than_s,
                expired_only=expired_only,
                clear_failures=clear_failures,
                vacuum=vacuum,
            )
        return 0

    def vacuum_cache(self) -> None:
        """Reclaim and defragment response cache database file."""
        if self._cache is not None:
            self._cache.vacuum()

    def cache_stats(self) -> dict[str, object] | None:
        """Return statistics about response cache storage."""
        if self._cache is not None:
            return self._cache.stats()
        return None
