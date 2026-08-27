"""Backend-independent dataset facade.

The facade owns logical key/schema behavior while a file backend owns physical
encoding and publication. A phase can compose this class with JSONL, Parquet,
or the in-memory backend without embedding format-specific CRUD code.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Self

from .errors import SchemaMismatchError, StorageError
from .models import BatchReceipt, DatasetSpec, RunContext
from .predicates import QueryPlan, predicate_fields
from .protocols import BatchWriteBackend, FileBackend, Record


def _plan_fields(plan: QueryPlan | None) -> set[str]:
    if plan is None:
        return set()
    fields = set(plan.columns or ())
    fields.update(key.field for key in plan.order_by)
    for predicate in plan.predicates:
        fields.update(predicate_fields(predicate))
    return fields


class Dataset:
    """Logical dataset API composed over a physical file backend."""

    def __init__(
        self, backend: FileBackend, spec: DatasetSpec, run: RunContext
    ) -> None:
        self.backend = backend
        self.spec = spec
        self.run = run
        self._initialized = False

    def init(self) -> None:
        self.backend.init(spec=self.spec, run=self.run)
        self._initialized = True

    def _require_init(self) -> None:
        if not self._initialized:
            raise StorageError("dataset used before init()")

    def _validate_query(self, plan: QueryPlan | None) -> None:
        if plan is None or self.spec.field_names is None:
            return
        unknown = sorted(_plan_fields(plan) - set(self.spec.field_names))
        if unknown:
            raise SchemaMismatchError(
                f"query fields not in declared schema for {self.spec.name}: {unknown}"
            )

    def load(self, query: QueryPlan | None = None) -> Iterator[Record]:
        self._require_init()
        self._validate_query(query)
        yield from self.backend.load(query)

    def set(self, records: Iterable[Record]) -> int:
        self._require_init()
        # Validation happens before delegating so a malformed batch cannot be
        # partially persisted by a backend.
        items = [dict(record) for record in records]
        for record in items:
            self.spec.validate_record(record)
        return self.backend.set(items)

    def write_batch(self, records: Iterable[Record]) -> BatchReceipt:
        self._require_init()
        items = [dict(record) for record in records]
        for record in items:
            self.spec.validate_record(record)
        if isinstance(self.backend, BatchWriteBackend):
            return self.backend.write_batch(items)
        count = self.backend.set(items)
        return BatchReceipt(record_count=count, byte_count=0, durable=False)

    def delete(self, query: QueryPlan) -> int:
        self._require_init()
        self._validate_query(query)
        return self.backend.delete(query)

    def completed_keys(self, keys: Iterable[str]) -> set[str]:
        self._require_init()
        wanted = tuple(str(key) for key in keys)
        if not wanted:
            return set()
        plan = QueryPlan(
            columns=(self.spec.key_field,),
            predicates=QueryPlan.for_keys(self.spec.key_field, wanted).predicates,
        )
        return {str(record[self.spec.key_field]) for record in self.load(plan)}

    def commit(self) -> None:
        self._require_init()
        self.backend.commit()

    def close(self) -> None:
        self.backend.close()
        self._initialized = False

    def __enter__(self) -> Self:
        self.init()
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.close()
