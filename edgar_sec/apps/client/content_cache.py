"""Byte-bounded LRU for facade content: filing text and parsed sequences.

One budget covers every kind; parsed sequences are the retained tier and
raw text is capped to a small share (it re-reads from the document cache).
RAM refusals and evictions spill to a bounded disk tier, never a recompute.
"""

from __future__ import annotations

import dataclasses
import threading
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from edgar_sec.apps.client.disk_tier import DiskTier

_NODE_OVERHEAD_BYTES = 64
_SCALAR_BYTES = 8

ContentKey = tuple[str, str]
WeightedBuilder = Callable[[], tuple[Any, int]]
ContentCodec = tuple[
    Callable[[Any], bytes], Callable[[bytes], Any], Callable[[Any], str]
]


def estimate_retained_bytes(value: object) -> int:
    """Estimate retained bytes of an acyclic object graph, shared nodes once."""
    seen: set[int] = set()
    total = 0
    stack: list[object] = [value]
    while stack:
        node = stack.pop()
        marker = id(node)
        if marker in seen:
            continue
        seen.add(marker)
        if isinstance(node, str):
            total += len(node)
        elif isinstance(node, (bytes, bytearray)):
            total += len(node)
        elif isinstance(node, dict):
            total += _NODE_OVERHEAD_BYTES + _SCALAR_BYTES * len(node)
            for key, item in node.items():
                stack.append(key)
                stack.append(item)
        elif isinstance(node, (tuple, list, set, frozenset)):
            total += _NODE_OVERHEAD_BYTES + _SCALAR_BYTES * len(node)
            stack.extend(node)
        elif dataclasses.is_dataclass(node) and not isinstance(node, type):
            total += _NODE_OVERHEAD_BYTES
            for field in dataclasses.fields(node):
                stack.append(getattr(node, field.name))
        else:
            total += _SCALAR_BYTES
    return total


class ContentCache:
    """One byte-bounded LRU over namespaced facade content, disk-backed.

    Builds run under a per-key lock, so a key is derived at most once; RAM
    refusals and evictions of codec-registered kinds spill to the disk tier.
    """

    def __init__(
        self,
        budget_bytes: int,
        *,
        max_item_fraction: float = 0.25,
        text_share: float = 0.125,
        text_kind: str = "text",
        disk_dir: Path | str | None = None,
        disk_budget_bytes: int | None = None,
        codecs: dict[str, ContentCodec] | None = None,
    ) -> None:
        if budget_bytes < 1:
            raise ValueError("content cache budget must be at least 1 byte")
        if not 0 < max_item_fraction <= 1:
            raise ValueError("max_item_fraction must be between 0 and 1")
        if not 0 < text_share <= 1:
            raise ValueError("text_share must be between 0 and 1")
        if (disk_dir is None) != (disk_budget_bytes is None):
            raise ValueError("disk_dir and disk_budget_bytes must be set together")
        self._codecs = dict(codecs or {})
        self._disk = (
            DiskTier(disk_dir, disk_budget_bytes)
            if disk_dir is not None and disk_budget_bytes is not None
            else None
        )
        self._budget = budget_bytes
        self._max_item_bytes = int(budget_bytes * max_item_fraction)
        self._text_cap = int(budget_bytes * text_share)
        self._text_kind = text_kind
        self._entries: OrderedDict[ContentKey, tuple[Any, int]] = OrderedDict()
        self._lock = threading.Lock()
        self._build_locks: dict[ContentKey, threading.Lock] = {}
        self._bytes = 0
        self._text_bytes = 0
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._bypassed = 0

    @property
    def budget_bytes(self) -> int:
        """Total byte budget shared by every kind."""
        return self._budget

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, key: ContentKey) -> bool:
        return key in self._entries

    def get(self, key: ContentKey) -> Any | None:
        """Return the cached value for key, from RAM or disk, or None."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                self._hits += 1
                self._entries.move_to_end(key)
                return entry[0]
            self._misses += 1
        value = self._disk_lookup(key)
        if value is None:
            return None
        with self._lock:
            evicted = self._admit_locked(key, value, estimate_retained_bytes(value))[1]
        self._spill(evicted)
        return value

    def get_or_build(self, key: ContentKey, builder: WeightedBuilder) -> Any:
        """Return the cached value for key, building and weighing it on a miss."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                self._entries.move_to_end(key)
                self._hits += 1
                return entry[0]
            self._misses += 1
            build_lock = self._build_locks.setdefault(key, threading.Lock())
        with build_lock:
            with self._lock:
                entry = self._entries.get(key)
                if entry is not None:
                    self._entries.move_to_end(key)
                    return entry[0]
            value = self._disk_lookup(key)
            from_disk = value is not None
            if from_disk:
                weight = estimate_retained_bytes(value)
            else:
                value, weight = builder()
            with self._lock:
                admitted, evicted = self._admit_locked(key, value, weight)
                if self._build_locks.get(key) is build_lock:
                    del self._build_locks[key]
            self._spill(evicted)
            if not admitted and not from_disk and weight > 0:
                self._spill([(key, value)])
            return value

    def clear(self) -> None:
        """Drop every entry on both tiers and reset the counters."""
        with self._lock:
            self._entries.clear()
            self._build_locks.clear()
            self._bytes = 0
            self._text_bytes = 0
            self._hits = 0
            self._misses = 0
            self._evictions = 0
            self._bypassed = 0
        if self._disk is not None:
            self._disk.clear()

    def stats(self) -> dict[str, Any]:
        """Return per-tier byte, budget, and outcome counters."""
        with self._lock:
            ram = {
                "entries": len(self._entries),
                "current_bytes": self._bytes,
                "budget_bytes": self._budget,
                "text_bytes": self._text_bytes,
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "bypassed_oversize": self._bypassed,
            }
        disk = self._disk.stats() if self._disk is not None else None
        return {"ram": ram, "disk": disk}

    def _disk_lookup(self, key: ContentKey) -> Any | None:
        """Decode a disk-tier value for key, or None on a miss or bad payload."""
        if self._disk is None:
            return None
        codec = self._codecs.get(key[0])
        if codec is None:
            return None
        raw = self._disk.get(key[0], key[1])
        if raw is None:
            return None
        try:
            return codec[1](raw)
        except Exception:
            self._disk.delete(key[0], key[1])
            return None

    def _spill(self, evicted: list[tuple[ContentKey, Any]]) -> None:
        """Write refused or evicted derivations to the disk tier."""
        if self._disk is None:
            return
        for key, value in evicted:
            codec = self._codecs.get(key[0])
            if codec is None:
                continue
            encode, _decode, source_id = codec
            try:
                payload = encode(value)
            except Exception:
                continue
            self._disk.put(key[0], key[1], payload, source_id(value))

    def _admit_locked(
        self, key: ContentKey, value: Any, weight: int
    ) -> tuple[bool, list[tuple[ContentKey, Any]]]:
        evicted: list[tuple[ContentKey, Any]] = []
        if weight <= 0:
            return False, evicted
        is_text = key[0] == self._text_kind
        limit = self._text_cap if is_text else self._max_item_bytes
        if weight > limit:
            self._bypassed += 1
            return False, evicted
        existing = self._entries.pop(key, None)
        if existing is not None:
            self._deduct_locked(key, existing[1])
        if is_text:
            while self._text_bytes + weight > self._text_cap:
                oldest = self._evict_oldest_locked(kind=self._text_kind)
                if oldest is None:
                    break
                evicted.append(oldest)
            while self._bytes + weight > self._budget:
                oldest = self._evict_oldest_locked(kind=self._text_kind)
                if oldest is None:
                    self._bypassed += 1
                    return False, evicted
                evicted.append(oldest)
        else:
            while self._bytes + weight > self._budget:
                oldest = self._evict_oldest_locked()
                if oldest is None:
                    self._bypassed += 1
                    return False, evicted
                evicted.append(oldest)
        self._entries[key] = (value, weight)
        self._bytes += weight
        if is_text:
            self._text_bytes += weight
        return True, evicted

    def _deduct_locked(self, key: ContentKey, weight: int) -> None:
        self._bytes -= weight
        if key[0] == self._text_kind:
            self._text_bytes -= weight

    def _evict_oldest_locked(
        self, kind: str | None = None
    ) -> tuple[ContentKey, Any] | None:
        for key in self._entries:
            if kind is None or key[0] == kind:
                value, weight = self._entries.pop(key)
                self._deduct_locked(key, weight)
                self._evictions += 1
                return key, value
        return None


__all__ = ["ContentCache", "ContentCodec", "ContentKey", "estimate_retained_bytes"]
