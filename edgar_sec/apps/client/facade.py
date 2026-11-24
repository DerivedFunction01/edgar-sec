"""High-level Edgar facade providing ergonomic querying, fetching, and inspection."""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from edgar_sec.apps.client.caching.cache import DocumentCache, get_default_cache
from edgar_sec.apps.client.caching.content_cache import ContentCache, ContentCodec
from edgar_sec.apps.client.core.sequence_codec import (
    decode_notes,
    decode_sections,
    encode_notes,
    encode_sections,
)
from edgar_sec.apps.client.facade_acquisition import AcquisitionMixin
from edgar_sec.apps.client.facade_cache_admin import CacheAdminMixin
from edgar_sec.apps.client.facade_capacity import (
    derive_content_cache_budget,
    derive_content_disk_budget,
    derive_facade_capacity,
)
from edgar_sec.apps.client.facade_content import ContentMixin
from edgar_sec.apps.client.facade_stored import StoredAccessMixin
from edgar_sec.apps.client.facade_xbrl import XbrlMixin
from edgar_sec.apps.client.reference.series_class import SeriesClassSurfaces
from edgar_sec.apps.client.surfaces import FeedSearchSurfaces
from edgar_sec.domain.identity import Cik
from edgar_sec.infra.sec_http.client import SecHttpClient

if TYPE_CHECKING:
    from edgar_sec.apps.client.financials.entity import Company
    from edgar_sec.apps.client.xbrl import Xbrl


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


class Edgar(
    AcquisitionMixin,
    StoredAccessMixin,
    CacheAdminMixin,
    XbrlMixin,
    ContentMixin,
    FeedSearchSurfaces,
    SeriesClassSurfaces,
):
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

    def company(self, identifier: str | int | Cik) -> Company:
        """Resolve an entity by ticker or CIK and return a Company model."""
        from edgar_sec.apps.client.financials.entity import Company
        from edgar_sec.apps.client.reference.resolver import resolve_entity_profile

        profile = resolve_entity_profile(identifier, self.artifacts_root)
        return Company(profile=profile, facade=self)


__all__ = [
    "Edgar",
    "FacadeCache",
]
