"""Dataset path safety and Parquet checks for cohort maintenance."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.foundation.runtime.settings.parquet import (
    resolve_parquet_read_batch_size,
)

from .paths import CohortPaths


def _resolved_dataset(paths: CohortPaths, dataset_path: str) -> Path:
    target = paths.resolve_relative_path(dataset_path)
    lexical = paths.cohorts_root.joinpath(*Path(dataset_path).parts)
    cursor = paths.cohorts_root
    for part in Path(dataset_path).parts:
        if cursor.is_symlink():
            raise ValueError(
                f"cohort dataset path contains a symlink: {dataset_path!r}"
            )
        cursor = cursor / part
    if lexical.is_symlink():
        raise ValueError(f"cohort dataset path is a symlink: {dataset_path!r}")
    return target


def _parquet_findings(dataset: Path, row_count: int | None = None) -> tuple[str, ...]:
    try:
        parquet = pq.ParquetFile(dataset)
        schema = parquet.schema_arrow
        expected = {
            "ordinal": pa.int64(),
            "cik_padded": pa.string(),
            "name": pa.string(),
        }
        for column, data_type in expected.items():
            if column not in schema.names or schema.field(column).type != data_type:
                return (f"invalid Parquet schema in {dataset}",)
        actual_rows = 0
        for batch in parquet.iter_batches(batch_size=resolve_parquet_read_batch_size()):
            actual_rows += batch.num_rows
        if row_count is not None and actual_rows != row_count:
            return (
                f"Parquet row count mismatch in {dataset}: {actual_rows} != {row_count}",
            )
    except Exception as exc:
        return (f"corrupt Parquet file {dataset}: {exc}",)
    return ()


def _family_index_findings(dataset: Path) -> tuple[str, ...]:
    expected = {
        "cik",
        "company_family",
        "family_kind",
        "sponsor_key",
        "assignment_rule",
    }
    try:
        parquet = pq.ParquetFile(dataset)
        if not expected.issubset(parquet.schema_arrow.names):
            return (f"invalid family-index schema in {dataset}",)
        for _ in parquet.iter_batches(batch_size=resolve_parquet_read_batch_size()):
            pass
    except Exception as exc:
        return (f"corrupt family-index Parquet file {dataset}: {exc}",)
    return ()
