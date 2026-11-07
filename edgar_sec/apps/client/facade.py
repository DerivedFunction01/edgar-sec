"""High-level Edgar facade providing ergonomic querying, fetching, and inspection."""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Sequence

from edgar_sec.apps.client.cache import DocumentCache, get_default_cache
from edgar_sec.apps.client.content_cache import (
    ContentCache,
    ContentCodec,
    estimate_retained_bytes,
)
from edgar_sec.apps.client.fast_query.query import query_catalog_fast
from edgar_sec.apps.client.sequence_codec import (
    decode_notes,
    decode_sections,
    encode_notes,
    encode_sections,
)
from edgar_sec.apps.client.models import FilingsResult
from edgar_sec.apps.runner.config import DateFilterInput, FilingQuery, PipelineConfig
from edgar_sec.apps.runner.coordinator import PipelineRunner
from edgar_sec.domain.identity import Cik
from edgar_sec.foundation.runtime.resources import (
    MEBIBYTE,
    RuntimeResourceProfile,
    derive_resources,
)
from edgar_sec.infra.sec_http.client import SecHttpClient

if TYPE_CHECKING:
    from edgar_sec.apps.client.efts import EftsCapture, EftsQuery, EftsSearchResult
    from edgar_sec.apps.client.entity import Company
    from edgar_sec.apps.client.feeds import FeedEventsResult
    from edgar_sec.apps.client.xbrl import Xbrl
    from edgar_sec.infra.storage.bulk_archive import (
        ArchiveReference,
        BulkArchiveStore,
    )
    from edgar_sec.domain.document.aggregate import FilingAggregate
    from edgar_sec.engine.forms.cover.toc.models import TocSpan
    from edgar_sec.engine.forms.sections.models import (
        NotesSequence,
        SectionSequence,
    )
    from edgar_sec.apps.client.snapshots import SnapshotConsole
    from edgar_sec.engine.xbrl.schema.models import FilingXbrl


# Mean retained bytes per live facade, from the facade memory profile.
_RETAINED_BYTES_PER_FACADE = int(6.9 * MEBIBYTE)


def derive_facade_capacity(resources: RuntimeResourceProfile | None = None) -> int:
    """Facade count one worker memory share holds at the measured per-facade cost."""
    profile = resources if resources is not None else derive_resources()
    budget_bytes = profile.worker_memory_mib * MEBIBYTE
    return max(1, budget_bytes // _RETAINED_BYTES_PER_FACADE)


def derive_content_cache_budget(
    resources: RuntimeResourceProfile | None = None,
) -> int:
    """Content-cache byte budget: a settings fraction of one worker memory share."""
    from edgar_sec.foundation.runtime.settings import resolve_settings

    profile = resources if resources is not None else derive_resources()
    fraction = float(
        resolve_settings(include=["client"])["client.content_cache_fraction"]
    )
    return max(1, int(profile.worker_memory_mib * MEBIBYTE * fraction))


def derive_content_disk_budget() -> int:
    """Disk-tier byte budget for spilled derivations, from the settings seam."""
    from edgar_sec.foundation.runtime.settings import resolve_settings

    return int(resolve_settings(include=["client"])["client.content_disk_budget_bytes"])


_CONTENT_CODECS: dict[str, ContentCodec] = {
    "sections": (
        encode_sections,
        decode_sections,
        lambda seq: seq.payload_sha256 or "",
    ),
    "notes": (
        encode_notes,
        decode_notes,
        lambda seq: seq.payload_sha256 or "",
    ),
}


class FacadeCache:
    """Bounded LRU of live facades; eviction drops the whole kernel.

    A hit returns the identical facade object; builds run under a
    per-key lock, so a key is constructed at most once, never convoyed.
    """

    def __init__(self, capacity: int | None = None) -> None:
        self._capacity = capacity if capacity is not None else derive_facade_capacity()
        if self._capacity < 1:
            raise ValueError("facade cache capacity must be at least 1")
        self._entries: OrderedDict[tuple[str, str], Xbrl] = OrderedDict()
        self._lock = threading.Lock()
        self._build_locks: dict[tuple[str, str], threading.Lock] = {}

    @property
    def capacity(self) -> int:
        """Maximum number of facades retained."""
        return self._capacity

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, key: tuple[str, str]) -> bool:
        return key in self._entries

    def get_or_build(self, key: tuple[str, str], builder: Callable[[], Xbrl]) -> Xbrl:
        """Return the cached facade for key, building and caching it on a miss."""
        with self._lock:
            facade = self._entries.get(key)
            if facade is not None:
                self._entries.move_to_end(key)
                return facade
            build_lock = self._build_locks.setdefault(key, threading.Lock())
        with build_lock:
            with self._lock:
                facade = self._entries.get(key)
                if facade is not None:
                    self._entries.move_to_end(key)
                    return facade
            facade = builder()
            with self._lock:
                self._entries[key] = facade
                while len(self._entries) > self._capacity:
                    self._entries.popitem(last=False)
                if self._build_locks.get(key) is build_lock:
                    del self._build_locks[key]
            return facade

    def clear(self) -> None:
        """Drop every cached facade."""
        with self._lock:
            self._entries.clear()
            self._build_locks.clear()


class Edgar:
    """Convenience client for querying, acquiring, and analyzing SEC filings."""

    def __init__(
        self,
        *,
        artifacts_root: Path | str | None = None,
        sec_client: SecHttpClient | None = None,
        workers: int | None = None,
        cache: DocumentCache | None = None,
        facade_capacity: int | None = None,
        content_cache_budget: int | None = None,
        content_disk_budget: int | None = None,
    ) -> None:
        self.artifacts_root = (
            Path(artifacts_root) if artifacts_root is not None else None
        )
        self.workers = workers
        self._sec_client = sec_client
        self._cache = cache
        self._facade_capacity = facade_capacity
        self._facade_cache: FacadeCache | None = None
        self._content_cache_budget = content_cache_budget
        self._content_disk_budget = content_disk_budget
        self._content_cache: ContentCache | None = None

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

    @property
    def facade_cache(self) -> FacadeCache:
        """Return the bounded LRU cache of live XBRL facades."""
        if self._facade_cache is None:
            self._facade_cache = FacadeCache(self._facade_capacity)
        return self._facade_cache

    @property
    def content_cache(self) -> ContentCache:
        """Return the byte-bounded LRU over filing text and parsed sequences."""
        if self._content_cache is None:
            from edgar_sec.foundation.runtime.paths import resolve_paths

            budget = self._content_cache_budget
            if budget is None:
                budget = derive_content_cache_budget()
            disk_budget = self._content_disk_budget
            if disk_budget is None:
                disk_budget = derive_content_disk_budget()
            root = (
                self.artifacts_root
                if self.artifacts_root is not None
                else resolve_paths().artifacts_root
            )
            self._content_cache = ContentCache(
                budget,
                disk_dir=root / "cache" / "content",
                disk_budget_bytes=disk_budget,
                codecs=_CONTENT_CODECS,
            )
        return self._content_cache

    def _bulk_archive_store(self) -> "BulkArchiveStore":
        from edgar_sec.infra.storage.bulk_archive import BulkArchiveStore
        from edgar_sec.pipelines.metadata_sync.paths import resolve_metadata_paths

        metadata = resolve_metadata_paths(self.artifacts_root)
        return BulkArchiveStore(metadata.bulk_archives_root)

    def bulk_archive(
        self, source_id: str, sha256: str | None = None
    ) -> "ArchiveReference | None":
        """Reference to a stored bulk archive, or ``None`` when unstored.

        Read-only: the facade never downloads; absence is reported, not
        repaired. The reference carries identity, manifest, and stored paths.
        """
        return self._bulk_archive_store().open(source_id, sha256)

    def bulk_archive_member(
        self, source_id: str, member_name: str, sha256: str | None = None
    ) -> bytes | None:
        """One member's bytes from a stored bulk archive.

        ``None`` when the source is unstored; an unknown member of a stored
        archive raises, as the store does.
        """
        store = self._bulk_archive_store()
        reference = store.open(source_id, sha256)
        if reference is None:
            return None
        return store.read_member(reference, member_name)

    def feed_events(
        self,
        *,
        forms: Sequence[str] | str = (),
        sources: Sequence[str] | str = (),
        filed_from: date | str | None = None,
        filed_to: date | str | None = None,
        limit: int | None = None,
    ) -> "FeedEventsResult":
        """Structured-disclosure events from the published feeds ledger.

        Read-only: an unstored ledger is reported as absence
        (``ledger_present`` is False), never repaired with a live fetch.
        """
        from edgar_sec.apps.client.feeds import read_feed_events

        return read_feed_events(
            self.artifacts_root,
            forms=(forms,) if isinstance(forms, str) else tuple(forms),
            sources=(sources,) if isinstance(sources, str) else tuple(sources),
            filed_from=filed_from,
            filed_to=filed_to,
            limit=limit,
        )

    def full_text_search(
        self,
        query: EftsQuery | None = None,
        *,
        text: str = "",
        forms: Sequence[str] = (),
        ciks: Sequence[str | int] = (),
        tickers: Sequence[str] = (),
        items: Sequence[str] = (),
        startdt: str | None = None,
        enddt: str | None = None,
        sec_syntax: str | None = None,
        max_hits: int | None = None,
        exhaustive: bool = False,
    ) -> EftsSearchResult:
        """Search the SEC full-text index live; nothing is persisted.

        Accepts an ``EftsQuery`` or query parts; tickers resolve to CIKs.
        ``exhaustive`` date-slices past the ceiling, requiring a date pair.
        """
        from edgar_sec.apps.client.efts import (
            EftsQuery,
            full_text_search,
            search_all,
        )

        resolved_ciks = tuple(str(c) for c in ciks)
        for ticker in tickers:
            from edgar_sec.apps.client.resolver import resolve_entity_profile

            profile = resolve_entity_profile(ticker, self.artifacts_root)
            if profile.cik.value == 1 and profile.name == str(ticker):
                raise ValueError(f"unresolved ticker: {ticker!r}")
            resolved_ciks += (profile.cik.to_10digit(),)
        if query is None:
            query = EftsQuery(
                text=text,
                forms=tuple(str(f) for f in forms),
                ciks=resolved_ciks,
                items=tuple(str(i) for i in items),
                startdt=startdt,
                enddt=enddt,
                sec_syntax=sec_syntax,
            )
        elif resolved_ciks:
            query = EftsQuery(
                text=query.text,
                forms=query.forms,
                ciks=tuple(query.ciks) + resolved_ciks,
                items=query.items,
                startdt=query.startdt,
                enddt=query.enddt,
                sec_syntax=query.sec_syntax,
            )
        if exhaustive:
            return search_all(query, client=self.sec_client, exhaustive=True)
        return full_text_search(query, client=self.sec_client, max_hits=max_hits)

    def capture_full_text_search(
        self,
        query: EftsQuery,
        *,
        exhaustive: bool = False,
    ) -> EftsCapture:
        """Run a search and write its explicit capture artefact.

        The only persistence path for a search: a plain
        ``full_text_search`` call writes nothing.
        """
        from edgar_sec.apps.client.efts import capture_full_text_search

        return capture_full_text_search(
            query,
            client=self.sec_client,
            artifacts_root=self.artifacts_root,
            exhaustive=exhaustive,
        )

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
        operation: str | None = None,
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
        op_list = (
            tuple(operations)
            if operations
            else ((operation,) if operation is not None else ())
        )

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
                operation=op_list[0] if op_list else None,
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

    def xbrl(self, filing: FilingAggregate) -> Xbrl:
        """Parse linkbases and return unified interactive Xbrl facade."""
        from edgar_sec.apps.client.xbrl import Xbrl
        from edgar_sec.engine.xbrl.parsing.filing_parser import parse_filing_xbrl

        key = (filing.primary_cik.to_10digit(), filing.accession.value)
        return self.facade_cache.get_or_build(
            key, lambda: Xbrl(parse_filing_xbrl(filing))
        )

    def sections(
        self, filing: FilingAggregate, text: str | None = None
    ) -> SectionSequence:
        """Detect and return full statutory Part/Item section sequence."""
        from edgar_sec.engine.forms.sections.models import SectionSequence

        if not filing.has_sections:
            return SectionSequence(sections=(), family=filing.form)

        if text is not None:
            return self._detect_sections(filing, text)
        return self.content_cache.get_or_build(
            ("sections", filing.accession.value),
            lambda: self._build_sections(filing),
        )

    def _build_sections(self, filing: FilingAggregate) -> tuple[SectionSequence, int]:
        body = self._extract_filing_text(filing)
        seq = self._detect_sections(filing, body)
        return seq, estimate_retained_bytes(seq) if body else 0

    def _detect_sections(self, filing: FilingAggregate, body: str) -> SectionSequence:
        from edgar_sec.engine.forms.sections.models import SectionSequence

        if not body:
            return SectionSequence(sections=(), family=filing.form)

        from edgar_sec.domain.forms.common.aliases import resolve_alias
        from edgar_sec.domain.forms.common.processing import profile_version_of
        from edgar_sec.domain.forms.families.processing_profiles import (
            get_family_entry,
        )
        from edgar_sec.engine.forms.sections.items.detector import (
            detect_section_sequence,
        )

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
            renderer_version=profile_version_of(
                entry.profile if entry is not None else None
            ),
        )

    def section(
        self, filing: FilingAggregate, item: str, text: str | None = None
    ) -> str:
        """Extract and return text of a specific section (e.g. 'ITEM 1A')."""
        if not filing.has_sections:
            return ""
        body = text if text is not None else self._extract_filing_text(filing)
        if not body:
            return ""
        seq = self.sections(filing, text=body)
        return seq.get_text(body, item)

    def notes(self, filing: FilingAggregate, text: str | None = None) -> NotesSequence:
        """Detect and return financial statement footnotes."""
        from edgar_sec.engine.forms.sections.models import NotesSequence

        if not filing.has_notes:
            return NotesSequence(notes=())

        if text is not None:
            return self._detect_notes(filing, text)
        return self.content_cache.get_or_build(
            ("notes", filing.accession.value),
            lambda: self._build_notes(filing),
        )

    def _build_notes(self, filing: FilingAggregate) -> tuple[NotesSequence, int]:
        body = self._extract_filing_text(filing)
        seq = self._detect_notes(filing, body)
        return seq, estimate_retained_bytes(seq) if body else 0

    def _detect_notes(self, filing: FilingAggregate, body: str) -> NotesSequence:
        from edgar_sec.domain.forms.common.processing import profile_version_of
        from edgar_sec.domain.forms.families.processing_profiles import (
            get_family_profile,
        )
        from edgar_sec.engine.forms.sections.models import NotesSequence
        from edgar_sec.engine.forms.sections.notes.detector import (
            detect_notes_sequence,
        )

        if not body:
            return NotesSequence(notes=())

        return detect_notes_sequence(
            body,
            renderer_version=profile_version_of(get_family_profile(filing.form)),
        )

    def note(
        self,
        filing: FilingAggregate,
        number: int | str,
        text: str | None = None,
    ) -> str:
        """Extract and return clean text of a specific financial note."""
        if not filing.has_notes:
            return ""
        body = text if text is not None else self._extract_filing_text(filing)
        if not body:
            return ""
        seq = self.notes(filing, text=body)
        try:
            num = (
                int(number)
                if isinstance(number, int)
                else int("".join(c for c in str(number) if c.isdigit()))
            )
        except (ValueError, TypeError):
            return ""
        return seq.get_text(body, num)

    def toc(self, filing: FilingAggregate, text: str | None = None) -> TocSpan | None:
        """Return detected Table of Contents span if present."""
        if not filing.has_toc:
            return None
        body = text if text is not None else self._extract_filing_text(filing)
        if not body:
            return None
        from edgar_sec.engine.forms.cover.toc.finder import find_toc_span

        return find_toc_span(body)

    def _extract_filing_text(self, filing: FilingAggregate) -> str:
        return self.content_cache.get_or_build(
            ("text", filing.accession.value),
            lambda: self._read_filing_text(filing),
        )

    def _read_filing_text(self, filing: FilingAggregate) -> tuple[str, int]:
        from edgar_sec.domain.forms.reports import CompanyReport

        report = filing.as_report()
        if isinstance(report, CompanyReport):
            text = report.text() or ""
            return text, len(text)
        return "", 0


__all__ = [
    "Edgar",
    "FacadeCache",
    "derive_content_cache_budget",
    "derive_content_disk_budget",
    "derive_facade_capacity",
]
