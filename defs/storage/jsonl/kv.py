"""Mutable keyed JSONL backend with write-ahead logging."""

from __future__ import annotations

import os
import threading
from collections.abc import Iterable

from ..errors import (
    MalformedArtifact,
    SchemaMismatchError,
    StorageError,
)
from ..models import BatchReceipt, DatasetSpec, RunContext
from ..predicates import Eq, InSet, QueryPlan, conjunction, evaluate_query
from ..protocols import Record
from .codec import JsonlCodec
from .wal import JsonlWal


class JsonlKeyValueBackend:
    """Mutable keyed JSONL backend with append-only WAL writes."""

    format_name = "jsonl-kv"

    def __init__(
        self,
        data_path: str,
        *,
        max_wal_entries: int = 1000,
        max_wal_bytes: int = 1_048_576,
    ) -> None:
        self.data_path = data_path
        self.wal = JsonlWal(
            data_path, max_entries=max_wal_entries, max_bytes=max_wal_bytes
        )
        self._spec: DatasetSpec | None = None
        self._data: dict[str, Record] | None = None
        self._lock = threading.RLock()

    def init(self, *, spec: DatasetSpec, run: RunContext) -> None:
        self._spec = spec
        os.makedirs(os.path.dirname(os.path.abspath(self.data_path)), exist_ok=True)

    def _require_spec(self) -> DatasetSpec:
        if self._spec is None:
            raise StorageError("backend used before init(spec=..., run=...)")
        return self._spec

    def _load_map(self) -> dict[str, Record]:
        spec = self._require_spec()
        data: dict[str, Record] = {}
        if os.path.exists(self.data_path):
            with open(self.data_path, "r", encoding="utf-8") as fh:
                for number, line in enumerate(fh, start=1):
                    if not line.strip():
                        continue
                    try:
                        record = JsonlCodec.decode(line, key_field=spec.key_field)
                        spec.validate_record(record)
                    except (MalformedArtifact, SchemaMismatchError) as exc:
                        raise MalformedArtifact(
                            f"{self.data_path} line {number}: {exc}"
                        ) from exc
                    data[str(record[spec.key_field])] = record
        for number, delta in enumerate(self.wal.replay(), start=1):
            op = delta.get("op")
            key = delta.get("key")
            if key in (None, ""):
                raise MalformedArtifact(f"WAL entry {number} has no key")
            if op == "set":
                record = dict(delta.get("value") or {})
                record[spec.key_field] = str(key)
                spec.validate_record(record)
                data[str(key)] = record
            elif op == "delete":
                data.pop(str(key), None)
            else:
                raise MalformedArtifact(f"unknown WAL op {op!r} in {self.wal.wal_path}")
        return data

    def _ensure_loaded(self) -> dict[str, Record]:
        if self._data is None:
            self._data = self._load_map()
        return self._data

    def load(self, query: QueryPlan | None = None) -> Iterable[Record]:
        with self._lock:
            records = list(self._ensure_loaded().values())
        return evaluate_query(records, query)

    def set(self, records: Iterable[Record]) -> int:
        spec = self._require_spec()
        items = [dict(record) for record in records]
        if not items:
            return 0
        deltas: list[dict] = []
        for record in items:
            spec.validate_record(record)
            key = str(record[spec.key_field])
            deltas.append({"op": "set", "key": key, "value": record})
        with self._lock:
            self.wal.append_many(deltas)
            if self._data is not None:
                for record in items:
                    self._data[str(record[spec.key_field])] = record
        return len(items)

    def write_batch(self, records: Iterable[Record]) -> BatchReceipt:
        spec = self._require_spec()
        items = [dict(record) for record in records]
        if not items:
            return BatchReceipt(record_count=0, byte_count=0, durable=True)
        for record in items:
            spec.validate_record(record)
        deltas = [
            {"op": "set", "key": str(record[spec.key_field]), "value": record}
            for record in items
        ]
        with self._lock:
            receipt = self.wal.append_many(deltas)
            if self._data is not None:
                for record in items:
                    self._data[str(record[spec.key_field])] = record
        return receipt

    def delete(self, query: QueryPlan) -> int:
        spec = self._require_spec()
        predicate = conjunction(query.predicates)
        with self._lock:
            data = self._ensure_loaded()
            if predicate is None:
                targets = list(data)
            elif isinstance(predicate, Eq) and predicate.field == spec.key_field:
                targets = [str(predicate.value)]
            elif isinstance(predicate, InSet) and predicate.field == spec.key_field:
                targets = [str(value) for value in predicate.values]
            else:
                targets = [
                    key for key, record in data.items() if predicate.matches(record)
                ]
            targets = [key for key in dict.fromkeys(targets) if key in data]
            if not targets:
                return 0
            receipt = self.wal.append_many(
                {"op": "delete", "key": key} for key in targets
            )
            if self._data is not None:
                for key in targets:
                    self._data.pop(key, None)
            return receipt.record_count

    def commit(self) -> None:
        self._require_spec()
        with self._lock:
            if not self.wal.exceeds_thresholds():
                return
            data = self._ensure_loaded()
            self.wal.reconcile(JsonlCodec.encode(record) for record in data.values())

    def close(self) -> None:
        return None


__all__ = ["JsonlKeyValueBackend"]
