"""High-level Edgar facade providing ergonomic querying, fetching, and inspection."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal, Sequence

from edgar_sec.apps.client.cache import DocumentCache, get_default_cache
from edgar_sec.apps.client.fast_query import query_catalog_fast
from edgar_sec.apps.client.models import FilingsResult
from edgar_sec.apps.runner.config import DateFilterInput, FilingQuery, PipelineConfig
from edgar_sec.apps.runner.coordinator import PipelineRunner
from edgar_sec.domain.identity import Cik
from edgar_sec.infra.sec_http.client import SecHttpClient

if TYPE_CHECKING:
    from edgar_sec.apps.client.entity import Company
    from edgar_sec.domain.document.aggregate import FilingAggregate
    from edgar_sec.engine.forms.cover.toc.models import TocSpan
    from edgar_sec.engine.forms.sections.models import (
        NotesSequence,
        SectionSequence,
    )
    from edgar_sec.apps.client.snapshots import SnapshotConsole
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

    def pipeline(self, config: PipelineConfig | FilingQuery) -> FilingsResult:
        """Execute end-to-end acquisition via the high-throughput pipeline runner."""
        if not isinstance(config, PipelineConfig):
            config = PipelineConfig(
                tickers=config.tickers,
                ciks=config.ciks,
                accessions=config.accessions,
                input_file=config.input_file,
                forms=config.forms,
                dates=config.dates,
                roles=config.roles,
                suffixes=config.suffixes,
                limit=config.limit,
                operations=config.operations,
                artifacts_root=self.artifacts_root,
                workers=self.workers,
                sec_client=self.sec_client,
            )
        runner = PipelineRunner(config)
        return runner.run(config)

    def fetch(
        self,
        query: FilingQuery | PipelineConfig | None = None,
        *,
        forms: Sequence[str] | str = (),
        ciks: Sequence[str | int] | str | int = (),
        tickers: Sequence[str] | str = (),
        accessions: Sequence[str] | str = (),
        dates: DateFilterInput = None,
        suffixes: Sequence[str] | str = (),
        roles: Sequence[str] | str = ("primary",),
        limit: int | None = None,
        operation: str = "raw",
        operations: Sequence[str] | str = (),
        family_operations: dict[str, str] | None = None,
        mode: Literal["fast", "pipeline", "snapshot"] = "fast",
        snapshot: str = "main",
        workers: int | None = None,
    ) -> FilingsResult:
        """Execute acquisition and return a relational FilingsResult."""
        if mode == "snapshot":
            from edgar_sec.apps.client.snapshots import (
                query_filings_from_snapshot,
            )

            form_tuple = (
                query.forms
                if query is not None
                else (
                    (forms,) if isinstance(forms, str) else tuple(str(f) for f in forms)
                )
            )
            cik_tuple = (
                query.ciks
                if query is not None
                else (
                    (str(ciks),)
                    if isinstance(ciks, (str, int))
                    else tuple(str(c) for c in ciks)
                )
            )
            date_filter = query.dates if query is not None else dates
            limit_val = query.limit if query is not None else limit
            return query_filings_from_snapshot(
                self.artifacts_root,
                snapshot_id_or_tag=snapshot,
                forms=form_tuple,
                ciks=cik_tuple,
                dates=date_filter,
                limit=limit_val,
            )

        if query is not None:
            if mode == "pipeline" or query.roles != ("primary",) or query.input_file:
                return self.pipeline(query)
            form_tuple = query.forms
            cik_tuple = query.ciks
            date_str = query.resolved_date_string()
            limit_val = query.limit
            op_val = query.operations[0] if query.operations else "raw"
            return query_catalog_fast(
                ciks=cik_tuple,
                forms=form_tuple,
                dates=date_str,
                limit=limit_val,
                operation=op_val,
                artifacts_root=self.artifacts_root,
                cache=self.cache,
                http_client_factory=(
                    (lambda: self.sec_client) if self.sec_client else None
                ),
            )

        form_tuple = (
            (forms,) if isinstance(forms, str) else tuple(str(f) for f in forms)
        )
        cik_tuple = (
            (str(ciks),)
            if isinstance(ciks, (str, int))
            else tuple(str(c) for c in ciks)
        )
        ticker_tuple = (
            (tickers,) if isinstance(tickers, str) else tuple(str(t) for t in tickers)
        )
        acc_tuple = (
            (accessions,)
            if isinstance(accessions, str)
            else tuple(str(a) for a in accessions)
        )
        role_tuple = (
            (roles,) if isinstance(roles, str) else tuple(str(r) for r in roles)
        )
        suffix_tuple = (
            (suffixes,)
            if isinstance(suffixes, str)
            else tuple(str(s) for s in suffixes)
        )
        op_list = tuple(operations) if operations else (operation,)

        q = FilingQuery(
            tickers=ticker_tuple,
            ciks=cik_tuple,
            accessions=acc_tuple,
            forms=form_tuple,
            dates=dates,
            roles=role_tuple,
            suffixes=suffix_tuple,
            limit=limit,
            operations=op_list,
        )
        if mode == "fast" and role_tuple == ("primary",) and not acc_tuple:
            resolved_ciks = list(cik_tuple)
            for t in ticker_tuple:
                from edgar_sec.apps.client.resolver import resolve_entity_profile

                prof = resolve_entity_profile(t, self.artifacts_root)
                if prof and prof.cik:
                    resolved_ciks.append(str(prof.cik.value))
            return query_catalog_fast(
                ciks=tuple(resolved_ciks),
                forms=form_tuple,
                dates=q.resolved_date_string(),
                limit=limit,
                operation=op_list[0] if op_list else "raw",
                family_operations=family_operations,
                artifacts_root=self.artifacts_root,
                cache=self.cache,
                http_client_factory=(
                    (lambda: self.sec_client) if self.sec_client else None
                ),
            )

        config = PipelineConfig(
            tickers=ticker_tuple,
            ciks=cik_tuple,
            accessions=acc_tuple,
            forms=form_tuple,
            dates=dates,
            roles=role_tuple,
            suffixes=suffix_tuple,
            limit=limit,
            operations=op_list,
            workers=workers if workers is not None else self.workers,
            sec_client=self.sec_client,
            artifacts_root=self.artifacts_root,
        )
        return self.pipeline(config)

    def fetch_from_file(
        self,
        file_path: Path | str,
        *,
        forms: Sequence[str] | str = (),
        roles: Sequence[str] | str = ("primary",),
        operation: str = "raw",
        operations: Sequence[str] | str = (),
        workers: int | None = None,
    ) -> FilingsResult:
        """Execute end-to-end acquisition against an arbitrary DuckDB-readable file."""
        op_list = tuple(operations) if operations else (operation,)
        config = PipelineConfig(
            input_file=Path(file_path),
            forms=(forms,) if isinstance(forms, str) else tuple(str(f) for f in forms),
            roles=(roles,) if isinstance(roles, str) else tuple(str(r) for r in roles),
            operations=op_list,
            workers=workers if workers is not None else self.workers,
            sec_client=self.sec_client,
            artifacts_root=self.artifacts_root,
        )
        return self.pipeline(config)

    def from_snapshot(
        self,
        snapshot_or_tag: str = "main",
        *,
        forms: Sequence[str] | str = (),
        ciks: Sequence[str | int] | str | int = (),
        dates: DateFilterInput = None,
        limit: int | None = None,
    ) -> FilingsResult:
        """Hydrate filings directly and offline from a published DAG snapshot."""
        from edgar_sec.apps.client.snapshots import query_filings_from_snapshot

        form_tuple = (
            (forms,) if isinstance(forms, str) else tuple(str(f) for f in forms)
        )
        cik_tuple = (
            (str(ciks),)
            if isinstance(ciks, (str, int))
            else tuple(str(c) for c in ciks)
        )
        return query_filings_from_snapshot(
            self.artifacts_root,
            snapshot_id_or_tag=snapshot_or_tag,
            forms=form_tuple,
            ciks=cik_tuple,
            dates=dates,
            limit=limit,
        )

    @property
    def snapshots(self) -> SnapshotConsole:
        """Return SnapshotConsole instance bound to this facade."""
        from edgar_sec.apps.client.snapshots import SnapshotConsole

        return SnapshotConsole(self.artifacts_root)

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

    def sections(
        self, filing: FilingAggregate, text: str | None = None
    ) -> SectionSequence:
        """Detect and return full statutory Part/Item section sequence."""
        from edgar_sec.domain.forms.common.aliases import resolve_alias
        from edgar_sec.domain.forms.families.processing_profiles import (
            get_family_entry,
        )
        from edgar_sec.engine.forms.sections.items.detector import (
            detect_section_sequence,
        )

        body = text if text is not None else self._extract_filing_text(filing)
        family = resolve_alias(filing.form) or filing.form.strip().upper()
        entry = get_family_entry(family)
        taxonomy = entry.taxonomy_items if entry is not None else ()
        toc_info = (
            self.toc(filing, text=body) if entry and entry.profile.has_toc else None
        )
        toc_span = (
            (toc_info.start_line, toc_info.end_line) if toc_info is not None else None
        )
        return detect_section_sequence(
            body,
            family=family,
            taxonomy_items=taxonomy,
            toc_span=toc_span,
        )

    def section(
        self, filing: FilingAggregate, item: str, text: str | None = None
    ) -> str:
        """Extract and return text of a specific section (e.g. 'ITEM 1A')."""
        body = text if text is not None else self._extract_filing_text(filing)
        seq = self.sections(filing, text=body)
        canon = item.upper().strip()
        if not canon.startswith("ITEM"):
            canon = f"ITEM {canon}"
        target = next((s for s in seq.sections if s.item_identifier == canon), None)
        if target is None:
            return ""
        lines = body.splitlines()
        end = target.end_line or len(lines)
        return "\n".join(lines[target.start_line : end])

    def notes(self, filing: FilingAggregate, text: str | None = None) -> NotesSequence:
        """Detect and return financial statement footnotes."""
        from edgar_sec.engine.forms.sections.notes.detector import (
            detect_notes_sequence,
        )

        body = text if text is not None else self._extract_filing_text(filing)
        return detect_notes_sequence(body)

    def note(
        self,
        filing: FilingAggregate,
        number: int | str,
        text: str | None = None,
    ) -> str:
        """Extract and return clean text of a specific financial note."""
        body = text if text is not None else self._extract_filing_text(filing)
        seq = self.notes(filing, text=body)
        num = int(str(number).replace("NOTE", "").strip())
        target = next((n for n in seq.notes if n.note_number == num), None)
        if target is None:
            return ""
        lines = body.splitlines()
        end = target.end_line or len(lines)
        return "\n".join(lines[target.start_line : end])

    def toc(self, filing: FilingAggregate, text: str | None = None) -> TocSpan | None:
        """Return detected Table of Contents span if present."""
        from edgar_sec.engine.forms.cover.toc.finder import find_toc_span

        body = text if text is not None else self._extract_filing_text(filing)
        return find_toc_span(body)

    def _extract_filing_text(self, filing: FilingAggregate) -> str:
        data = filing.raw()
        return data.decode("utf-8", errors="ignore") if data else ""


__all__ = ["Edgar"]
