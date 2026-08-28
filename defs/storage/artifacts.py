"""Backend-neutral readers for finalized dataset artifacts."""

from __future__ import annotations

import json
from collections.abc import Iterable

from .errors import MalformedArtifact, SchemaMismatchError
from .models import DatasetSpec


def read_records(path: str, storage_format: str, *, spec: DatasetSpec) -> list[dict]:
    """Read and validate one finalized Parquet or JSONL artifact."""
    if storage_format == "parquet":
        try:
            import pyarrow.parquet as pq

            if spec.arrow_schema is None:
                raise MalformedArtifact("Parquet artifact requires an Arrow schema")
            records: Iterable[dict] = pq.read_table(
                path, schema=spec.arrow_schema
            ).to_pylist()
        except (OSError, ValueError) as exc:
            raise MalformedArtifact(
                f"cannot read Parquet artifact {path}: {exc}"
            ) from exc
        except Exception as exc:  # backend-specific read errors
            raise MalformedArtifact(
                f"cannot read Parquet artifact {path}: {exc}"
            ) from exc
    elif storage_format == "jsonl":
        records = []
        number = 0
        try:
            with open(path, encoding="utf-8") as handle:
                for number, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    value = json.loads(line)
                    if not isinstance(value, dict):
                        raise ValueError("record is not an object")
                    records.append(value)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise MalformedArtifact(
                f"cannot read JSONL artifact {path} at line {number}: {exc}"
            ) from exc
    else:
        raise ValueError("storage_format must be 'parquet' or 'jsonl'")

    result = [dict(record) for record in records]
    for record in result:
        try:
            spec.validate_record(record)
        except (KeyError, TypeError, ValueError, SchemaMismatchError) as exc:
            raise MalformedArtifact(
                f"artifact schema validation failed for {path}: {exc}"
            ) from exc
    return result


__all__ = ["read_records"]
