"""Structural storage contracts (Python's analogue of TS interfaces).

``StorageBackend`` is the minimal mutating contract. Optional capabilities are
separate protocols so backends can adopt them without polluting the base
contract with format-specific operations.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol, runtime_checkable

from .models import ArtifactRef, BatchReceipt, ChunkRange, DatasetSpec, RunContext
from .predicates import QueryPlan

Record = dict[str, Any]
RecordKey = str


@runtime_checkable
class FileBackend(Protocol):
    """Minimal file backend contract: init/load/set/delete/commit/close.

    - ``set`` is an idempotent upsert by the dataset logical key and accepts a
      batch iterable.
    - ``delete`` applies a backend-neutral predicate plan and returns the
      number of records removed.
    - ``commit`` makes prior mutations durable; implementations choose the
      physical meaning (SQL commit, atomic file replacement, WAL flush).
    """

    def init(self, *, spec: DatasetSpec, run: RunContext) -> None: ...
    def load(self, query: QueryPlan | None = None) -> Iterable[Record]: ...
    def set(self, records: Iterable[Record]) -> int: ...
    def delete(self, query: QueryPlan) -> int: ...
    def commit(self) -> None: ...
    def close(self) -> None: ...


# Kept as a local alias for callers of the first draft of the storage layer.
# New code should use FileBackend so SQL executors are not mistaken for CRUD
# stores.
StorageBackend = FileBackend


@runtime_checkable
class BatchWriteBackend(Protocol):
    """Optional physical API for one-pass, batch-oriented writes."""

    def write_batch(self, records: Iterable[Record]) -> BatchReceipt: ...


@runtime_checkable
class ChunkStore(Protocol):
    """Immutable chunk artifacts for deterministic checkpoint workflows."""

    def write_chunk(
        self, chunk: ChunkRange, records: Iterable[Record]
    ) -> ArtifactRef: ...
    def list_chunks(self) -> list[ArtifactRef]: ...
    def load_chunk_records(self, chunk_id: int) -> list[Record]: ...
    def finalize(self, output_path: str) -> ArtifactRef: ...


@runtime_checkable
class WalStore(Protocol):
    """Append-log capability (JSONL adapters); replay must be idempotent."""

    def replay(self) -> Iterable[dict]: ...
    def compact(self) -> None: ...
