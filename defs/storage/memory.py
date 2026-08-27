"""In-memory reference backend.

Defines the reference semantics every physical backend must reproduce: batch
idempotent upsert, predicate delete/evaluation, and explicit commit as a
durability no-op. Also used by tests to validate domain classes without I/O.
"""

from __future__ import annotations

import threading
from typing import Iterable

from .errors import SchemaMismatchError, StorageError
from .models import BatchReceipt, DatasetSpec, RunContext
from .predicates import QueryPlan, conjunction, evaluate_query
from .protocols import Record


class MemoryBackend:
    def __init__(self) -> None:
        self._data: dict[str, Record] = {}
        self._spec: DatasetSpec | None = None
        self._run: RunContext | None = None
        self._lock = threading.RLock()

    def init(self, *, spec: DatasetSpec, run: RunContext) -> None:
        with self._lock:
            if (
                self._spec is not None
                and self._spec.schema_version != spec.schema_version
            ):
                raise SchemaMismatchError(
                    f"backend already initialized with schema {self._spec.schema_version}, "
                    f"got {spec.schema_version}"
                )
            self._spec = spec
            self._run = run

    def _require_spec(self) -> DatasetSpec:
        if self._spec is None:
            raise StorageErrorNotInitialized()
        return self._spec

    def load(self, query: QueryPlan | None = None) -> Iterable[Record]:
        self._require_spec()
        with self._lock:
            rows = list(self._data.values())
        return evaluate_query(rows, query)

    def set(self, records: Iterable[Record]) -> int:
        spec = self._require_spec()
        items = list(records)
        count = 0
        for record in items:
            spec.validate_record(record)
        with self._lock:
            for record in items:
                key = record[spec.key_field]
                if not isinstance(key, str):
                    raise SchemaMismatchError(
                        f"logical key {spec.key_field!r} must be a string"
                    )
                self._data[key] = dict(record)
                count += 1
        return count

    def write_batch(self, records: Iterable[Record]) -> BatchReceipt:
        count = self.set(records)
        return BatchReceipt(record_count=count, byte_count=0, durable=True)

    def delete(self, query: QueryPlan) -> int:
        self._require_spec()
        predicate = conjunction(query.predicates)
        removed = 0
        with self._lock:
            keys = [
                key
                for key, row in self._data.items()
                if predicate is None or predicate.matches(row)
            ]
            for key in keys:
                del self._data[key]
                removed += 1
        return removed

    def commit(self) -> None:
        self._require_spec()  # durability is inherent; nothing to do

    def close(self) -> None:
        return None


class StorageErrorNotInitialized(StorageError):
    def __init__(self) -> None:
        super().__init__("backend used before init(spec=..., run=...)")
