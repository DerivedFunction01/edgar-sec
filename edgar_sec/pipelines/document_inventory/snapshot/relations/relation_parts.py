"""Snapshot relation part descriptors and part writing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.runtime.paths import part_file_name
from edgar_sec.infra.storage.duckdb import copy_query_to_parquet
from edgar_sec.infra.storage.parquet import read_parquet_key_bounds
from edgar_sec.pipelines.document_inventory.paths import InventoryPaths
from edgar_sec.pipelines.document_inventory.snapshot.contracts.errors import (
    ValidationFailedError,
)
from edgar_sec.pipelines.document_inventory.snapshot.relations.merge_relations import (
    _RELATION_SCHEMAS,
)


def _write_part_descriptor(
    path: Path,
    relative_path: str,
    schema: pa.Schema,
    key_column: str,
) -> dict[str, Any]:
    parquet = pq.ParquetFile(path)
    key_min, key_max = read_parquet_key_bounds(path, key_column)
    if key_min is None or key_max is None:
        raise ValidationFailedError(f"snapshot part has no key values: {path}")
    if pq.ParquetFile(path).schema_arrow.names != schema.names:
        raise ValidationFailedError(f"snapshot part schema mismatch: {path}")
    return {
        "path": relative_path,
        "row_count": parquet.metadata.num_rows,
        "key_min": key_min,
        "key_max": key_max,
        "byte_size": path.stat().st_size,
        "sha256": file_sha256(path),
        "row_group_count": parquet.metadata.num_row_groups,
    }


def _key_range(path: Path, key_column: str) -> tuple[str | None, str | None]:
    return read_parquet_key_bounds(path, key_column)


def _relation_files(paths: InventoryPaths, records: list[dict[str, Any]]) -> list[Path]:
    result = []
    for record in records:
        relative = Path(record["path"])
        owner = relative.parts[0]
        resolved = (paths.snapshots_root / relative).resolve()
        resolved.relative_to(paths.snapshot_root(owner).resolve())
        result.append(resolved)
    return result


def _write_relation_part(
    con,
    stage_root: Path,
    snapshot_id: str,
    relation: str,
    query: str,
    key_column: str,
) -> dict[str, Any] | None:
    staged = stage_root / relation / part_file_name(0)
    staged.parent.mkdir(parents=True, exist_ok=True)
    count = copy_query_to_parquet(
        con, query, staged, schema=_RELATION_SCHEMAS[relation]
    )
    if count == 0:
        if staged.exists():
            staged.unlink()
        return None
    key_min, key_max = _key_range(staged, key_column)
    relative = f"{relation}/{part_file_name(0)}"
    return {
        "path": relative,
        "row_count": count,
        "key_min": key_min,
        "key_max": key_max,
        "byte_size": staged.stat().st_size,
        "sha256": file_sha256(staged),
        "row_group_count": pq.ParquetFile(staged).metadata.num_row_groups,
    }
