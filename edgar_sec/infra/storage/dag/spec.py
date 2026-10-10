"""Declarative relational specifications for snapshot tables.

Governs how delta tables combine with ancestors along a DAG lineage.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pyarrow as pa

from edgar_sec.foundation.runtime.settings.parquet import DEFAULT_ROW_GROUP_SIZE

MergeStrategy = Literal["upsert", "append", "scoped_mask"]


@dataclass(frozen=True, slots=True)
class RelationSpec:
    """Declarative relational schema and merge contract for a snapshot table."""

    name: str
    schema: pa.Schema
    primary_key: tuple[str, ...]
    merge_strategy: MergeStrategy
    sort_order: tuple[str, ...]
    parent_relation: str | None = None
    parent_join_key: tuple[str, ...] | None = None
    tie_breaker_column: str | None = None
    tie_breaker_op: Literal["min", "max"] = "min"
    max_rows_per_part: int | None = DEFAULT_ROW_GROUP_SIZE
    entity_key: str | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.name.isidentifier():
            raise ValueError(f"invalid relation name: {self.name!r}")
        if not self.primary_key:
            raise ValueError(f"relation {self.name} must define a primary key")
        schema_names = set(self.schema.names)
        if self.entity_key and self.entity_key not in schema_names:
            raise ValueError(
                f"entity_key {self.entity_key!r} not in schema for {self.name}"
            )
        if self.max_rows_per_part is not None and self.max_rows_per_part <= 0:
            raise ValueError(
                f"max_rows_per_part must be positive, got {self.max_rows_per_part}"
            )
        for col in self.primary_key:
            if col not in schema_names:
                raise ValueError(
                    f"primary key column {col!r} not in schema for {self.name}"
                )
        for col in self.sort_order:
            if col not in schema_names:
                raise ValueError(f"sort column {col!r} not in schema for {self.name}")
        if self.merge_strategy == "scoped_mask":
            if not self.parent_relation:
                raise ValueError(
                    f"scoped_mask relation {self.name} requires parent_relation"
                )
            if not self.parent_join_key:
                raise ValueError(
                    f"scoped_mask relation {self.name} requires parent_join_key"
                )
        if self.merge_strategy == "append" and self.tie_breaker_column:
            if self.tie_breaker_column not in schema_names:
                raise ValueError(
                    f"tie breaker {self.tie_breaker_column!r} not in schema"
                )
            if self.tie_breaker_op not in ("min", "max"):
                raise ValueError(f"invalid tie_breaker_op: {self.tie_breaker_op}")


__all__ = ["MergeStrategy", "RelationSpec"]
