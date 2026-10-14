"""High-level Edgar facade providing ergonomic querying, fetching, and inspection."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal, Sequence

from edgar_sec.apps.client.cache import DocumentCache, get_default_cache
from edgar_sec.apps.client.fast_query import query_catalog_fast
from edgar_sec.apps.client.models import FilingsResult
from edgar_sec.apps.runner.config import RunnerOptions, TargetSpec
from edgar_sec.apps.runner.coordinator import PipelineRunner
from edgar_sec.domain.identity import Cik
from edgar_sec.infra.sec_http.client import SecHttpClient

if TYPE_CHECKING:
    from edgar_sec.apps.client.entity import Company
    from edgar_sec.domain.document.aggregate import FilingAggregate
    from edgar_sec.engine.xbrl.schema.models import FilingXbrl


class Edgar:
    """Convenience client for querying, acquiring, and analyzing SEC filings."""

    def __init__(
        self,
        *,
        artifacts_root: Path | str | None = None,
        sec_client: SecHttpClient | None = None,
        workers: int | None = None,
        cache: DocumentCache | None = None,
    ) -> None:
        self.artifacts_root = (
            Path(artifacts_root) if artifacts_root is not None else None
        )
        self.workers = workers
        self._sec_client = sec_client
        self._cache = cache

    @property
    def sec_client(self) -> SecHttpClient:
        """Return SecHttpClient instance for this facade."""
        if self._sec_client is None:
            from edgar_sec.foundation.runtime.paths import resolve_paths

            root = (
                self.artifacts_root
                if self.artifacts_root is not None
                else resolve_paths().artifacts_root
            )
            self._sec_client = SecHttpClient(cache_dir=root / "cache")
        return self._sec_client

    @sec_client.setter
    def sec_client(self, value: SecHttpClient | None) -> None:
        self._sec_client = value

    @property
    def cache(self) -> DocumentCache:
        """Return DocumentCache instance for this facade."""
        if self._cache is None:
            self._cache = get_default_cache(self.artifacts_root)
        return self._cache

    def fetch(
        self,
        *,
        forms: Sequence[str] | str = (),
        ciks: Sequence[str | int] | str | int = (),
        dates: str | None = None,
        suffixes: Sequence[str] | str = (),
        role: str = "primary",
        limit: int | None = None,
        operation: str = "raw",
        family_operations: dict[str, str] | None = None,
        mode: Literal["fast", "pipeline"] = "fast",
        publish_snapshot: bool = False,
        workers: int | None = None,
    ) -> FilingsResult:
        """Execute acquisition and return a relational FilingsResult."""
        form_tuple = (
            (forms,) if isinstance(forms, str) else tuple(str(f) for f in forms)
        )
        cik_tuple = (
            (str(ciks),)
            if isinstance(ciks, (str, int))
            else tuple(str(c) for c in ciks)
        )
        if mode == "fast" and not publish_snapshot and role == "primary":
            return query_catalog_fast(
                ciks=cik_tuple,
                forms=form_tuple,
                dates=dates,
                limit=limit,
                artifacts_root=self.artifacts_root,
                cache=self.cache,
                http_client_factory=(
                    (lambda: self.sec_client) if self.sec_client else None
                ),
            )
        suffix_tuple = (
            (suffixes,)
            if isinstance(suffixes, str)
            else tuple(str(s) for s in suffixes)
        )
        spec = TargetSpec(
            forms=form_tuple,
            ciks=cik_tuple,
            dates=dates,
            suffixes=suffix_tuple,
            role=role,
            limit=limit,
        )
        effective_workers = workers if workers is not None else self.workers
        options = RunnerOptions(
            operation=operation,
            family_operations=family_operations or {},
            workers=effective_workers,
            sec_client=self.sec_client,
            artifacts_root=self.artifacts_root,
            publish_snapshot=publish_snapshot,
        )
        runner = PipelineRunner(options)
        return runner.run(spec)

    def fetch_from_file(
        self,
        file_path: Path | str,
        *,
        operation: str = "raw",
        family_operations: dict[str, str] | None = None,
        role: str = "primary",
        publish_snapshot: bool = False,
        workers: int | None = None,
    ) -> FilingsResult:
        """Execute end-to-end acquisition against an arbitrary DuckDB-readable file."""
        spec = TargetSpec(
            role=role,
            input_file=Path(file_path),
        )
        effective_workers = workers if workers is not None else self.workers
        options = RunnerOptions(
            operation=operation,
            family_operations=family_operations or {},
            workers=effective_workers,
            sec_client=self.sec_client,
            artifacts_root=self.artifacts_root,
            publish_snapshot=publish_snapshot,
        )
        runner = PipelineRunner(options)
        return runner.run(spec)

    def company(self, identifier: str | int | Cik) -> Company:
        """Resolve an entity by ticker or CIK and return a Company model."""
        from edgar_sec.apps.client.entity import Company
        from edgar_sec.apps.client.resolver import resolve_entity_profile

        profile = resolve_entity_profile(identifier, self.artifacts_root)
        return Company(profile=profile, facade=self)

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
        return client.cache_stats()

    def xbrl(self, filing: FilingAggregate) -> FilingXbrl:
        """Parse and return complete FilingXbrl bundle from filing linkbases."""
        from edgar_sec.engine.xbrl.parsing.filing_parser import parse_filing_xbrl

        return parse_filing_xbrl(filing)


__all__ = ["Edgar"]
