"""Dataset/run value objects shared by the storage facade and backends."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from .errors import SchemaMismatchError, StorageError

_SAFE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


@dataclass(frozen=True, slots=True)
class DatasetSpec:
    """Declarative description of one canonical dataset.

    ``arrow_schema`` (a :class:`pyarrow.Schema`) is optional: file backends
    that need a physical schema (Parquet) require it, while JSONL/SQL backends
    accept plain dict records validated against ``key_field`` and
    ``required_fields``.
    """

    name: str
    schema_version: str
    key_field: str = "cik"
    arrow_schema: Any | None = None  # pyarrow.Schema when provided
    required_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _SAFE_NAME_RE.match(self.name):
            raise StorageError(
                f"dataset name must match {_SAFE_NAME_RE.pattern}: {self.name!r}"
            )
        if not self.schema_version:
            raise StorageError("schema_version is required")
        if not self.key_field:
            raise StorageError("key_field is required")

    @property
    def field_names(self) -> tuple[str, ...] | None:
        if self.arrow_schema is None:
            return None
        return tuple(self.arrow_schema.names)

    def validate_record(self, record: dict) -> None:
        """Validate a single record shape against this spec."""
        if not isinstance(record, dict):
            raise SchemaMismatchError(
                f"record must be a dict, got {type(record).__name__}"
            )
        if record.get(self.key_field) in (None, ""):
            raise SchemaMismatchError(f"record missing logical key {self.key_field!r}")
        for name in self.required_fields:
            if name not in record:
                raise SchemaMismatchError(f"record missing required field {name!r}")
        field_names = self.field_names
        if field_names is not None:
            unknown = sorted(set(record) - set(field_names))
            if unknown:
                raise SchemaMismatchError(
                    f"record fields not in declared schema for {self.name}: {unknown}"
                )


@dataclass(frozen=True, slots=True)
class RunContext:
    """Identity of the producing run; embedded in chunk artifacts."""

    run_id: str
    input_fingerprint: str = ""
    created_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChunkRange:
    """Contiguous inclusive row range within a deterministic plan."""

    chunk_id: int
    start_row: int
    end_row: int

    def __post_init__(self) -> None:
        if self.chunk_id < 0:
            raise StorageError("chunk_id must be >= 0")
        if self.end_row < self.start_row:
            raise StorageError("chunk end_row must be >= start_row")

    @property
    def row_count(self) -> int:
        return self.end_row - self.start_row + 1


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    """Reference to a completed persisted artifact."""

    dataset: str
    version: str
    path: str
    format: str
    row_count: int
    bytes: int
    chunk_id: int | None = None
    start_row: int | None = None
    end_row: int | None = None


@dataclass(frozen=True, slots=True)
class BatchReceipt:
    """Result of a durable or staged batch write."""

    record_count: int
    byte_count: int
    durable: bool
    generation: int | None = None
    artifact: ArtifactRef | None = None


def make_spec(
    name: str,
    schema_version: str,
    key_field: str = "cik",
    arrow_schema: Optional[Any] = None,
    required_fields: tuple[str, ...] = (),
) -> DatasetSpec:
    return DatasetSpec(
        name=name,
        schema_version=schema_version,
        key_field=key_field,
        arrow_schema=arrow_schema,
        required_fields=required_fields,
    )
