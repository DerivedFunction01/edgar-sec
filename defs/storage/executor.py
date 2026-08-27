"""Unified logical storage-executor boundary.

One contract for every storage family. Domain classes depend only on
``StorageExecutor``; physical differences live behind it:

- ``FileStorageExecutor`` composes JSONL/Parquet/Memory file backends and
  applies logical operations through the backend's native append/transaction
  behavior.
- ``SqlStorageExecutor`` (phase-owned repositories) maps logical records to
  phase-specific relational tables and delegates compiled statements to
  ``defs.sql.executor.SqlExecutor``.

The logical record/column specification is identical across families; the
physical schema is not required to match (SQL may normalize one nested record
into several tables).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from .models import DatasetSpec
from .predicates import QueryPlan
from .protocols import Record


@dataclass(frozen=True, slots=True)
class SetRecords:
    records: tuple[Record, ...]

    def __init__(self, records: Iterable[Record]):
        object.__setattr__(self, "records", tuple(dict(r) for r in records))


@dataclass(frozen=True, slots=True)
class DeleteMatching:
    query: QueryPlan


StorageOperation = SetRecords | DeleteMatching


@runtime_checkable
class StorageExecutor(Protocol):
    """Logical storage contract shared by file and SQL families."""

    def init(self, spec: DatasetSpec, run: Any = None) -> None: ...
    def load(self, query: QueryPlan | None = None) -> Iterable[Record]: ...
    def load_one(self, query: QueryPlan) -> Record | None: ...
    def set(self, records: Iterable[Record]) -> int: ...
    def delete(self, query: QueryPlan) -> int: ...
    def transaction(self, operations: Iterable[StorageOperation]) -> None: ...
    def close(self) -> None: ...


class FileStorageExecutor:
    """Logical executor composed over any file backend.

    ``transaction`` applies operations sequentially against the composed
    backend, then requests a durable commit. File backends without mutation
    (chunk stores) raise their own unsupported-capability errors from ``set``.
    """

    def __init__(self, backend: Any) -> None:
        self.backend = backend
        self._spec: DatasetSpec | None = None

    def init(self, spec: DatasetSpec, run: Any = None) -> None:
        from .models import RunContext

        self._spec = spec
        self.backend.init(spec=spec, run=run or RunContext(run_id="unnamed"))

    def _require_spec(self) -> DatasetSpec:
        if self._spec is None:
            from .errors import StorageError

            raise StorageError("executor used before init(spec=...)")
        return self._spec

    def load(self, query: QueryPlan | None = None) -> Iterable[Record]:
        self._require_spec()
        return self.backend.load(query)

    def load_one(self, query: QueryPlan) -> Record | None:
        for record in self.load(query):
            return record
        return None

    def set(self, records: Iterable[Record]) -> int:
        self._require_spec()
        return self.backend.set(records)

    def delete(self, query: QueryPlan) -> int:
        self._require_spec()
        return self.backend.delete(query)

    def transaction(self, operations: Iterable[StorageOperation]) -> None:
        self._require_spec()
        # File backends cannot always roll back physical appends; replay
        # idempotency by key keeps retried transactions safe.
        for operation in operations:
            if isinstance(operation, SetRecords):
                self.backend.set(operation.records)
            elif isinstance(operation, DeleteMatching):
                self.backend.delete(operation.query)
            else:
                from .errors import StorageError

                raise StorageError(
                    f"unknown storage operation: {type(operation).__name__}"
                )
        self.backend.commit()

    def close(self) -> None:
        self.backend.close()


__all__ = [
    "DeleteMatching",
    "FileStorageExecutor",
    "SetRecords",
    "StorageExecutor",
    "StorageOperation",
]
