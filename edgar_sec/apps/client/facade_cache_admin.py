"""Cache and lifecycle administration surface of the Edgar facade."""

from __future__ import annotations

from typing import Literal

from edgar_sec.infra.sec_http.client import SecHttpClient


class CacheAdminMixin:
    """Cache administration methods composed into the Edgar facade."""

    def clean(
        self,
        scope: Literal["transient", "plans", "all"] = "all",
        run_id: str | None = None,
        plan_id: str | None = None,
    ) -> dict[str, int]:
        """Manual lifecycle cleanup for transient runs and plan bundles."""
        from edgar_sec.apps.runner.cleanup import clear_plans, clear_transient

        res = {"transient": 0, "plans": 0}
        if scope in ("transient", "all"):
            res["transient"] = clear_transient(self.artifacts_root, run_id=run_id)
        if scope in ("plans", "all"):
            res["plans"] = clear_plans(self.artifacts_root, plan_id=plan_id)
        return res

    def clear_cache(
        self,
        *,
        scope: Literal["all", "documents", "responses"] = "all",
        cik: str | int | None = None,
        accession: str | None = None,
        url: str | None = None,
        url_pattern: str | None = None,
        kind: str | None = None,
        older_than_s: int | float | None = None,
        expired_only: bool = False,
        clear_failures: bool = False,
        vacuum: bool = True,
    ) -> dict[str, int]:
        """Clear documents cache, responses cache, or both matching filters."""
        if self._content_cache is not None:
            self._content_cache.clear()
        if self._facade_cache is not None:
            self._facade_cache.clear()
        cleared: dict[str, int] = {"documents": 0, "responses": 0}
        if scope in ("all", "documents"):
            cleared["documents"] = self.cache.clear(accession=accession, cik=cik)
        if scope in ("all", "responses"):
            client = self.sec_client or SecHttpClient()
            cleared["responses"] = client.clear_cache(
                url=url,
                url_pattern=url_pattern,
                cik=cik,
                kind=kind,
                older_than_s=older_than_s,
                expired_only=expired_only,
                clear_failures=clear_failures,
                vacuum=vacuum,
            )
        return cleared

    def vacuum_cache(self) -> None:
        """Compact SQLite response database and reclaim free space."""
        client = self.sec_client or SecHttpClient()
        client.vacuum_cache()

    def cache_stats(self) -> dict[str, object] | None:
        """Return statistics describing the SQLite response cache."""
        client = self.sec_client or SecHttpClient()
        stats = client.cache_stats()
        if stats is None:
            return None
        extended = dict(stats)
        extended["content_cache"] = self.content_cache.stats()
        return extended
