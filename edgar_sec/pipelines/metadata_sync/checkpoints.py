"""Chunk checkpoint discovery and validation.

A chunk checkpoint is considered complete only when it exists, matches the
canonical schema, holds exactly the planned CIKs, and carries the expected
input fingerprint. Anything else is treated as absent so the chunk is refetched
rather than merged into a snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa

from edgar_sec.domain.submissions.schemas import SUBMISSION_METADATA_SCHEMA
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.parquet import count_parquet_rows, read_parquet_schema

from .paths import RunPaths

__all__ = [
    "ChunkInfo",
    "discover_completed_chunks",
    "inspect_chunk",
    "schema_matches",
]


@dataclass(frozen=True, slots=True)
class ChunkInfo:
    """A validated chunk checkpoint on disk."""

    chunk_id: int
    path: Path
    row_count: int
    ciks: tuple[str, ...]
    file_sha256: str

    @property
    def valid(self) -> bool:
        """Always true; instances are only constructed for valid checkpoints."""
        return True


def schema_matches(path: Path) -> bool:
    """True when a Parquet file's footer schema equals the canonical schema."""
    try:
        return read_parquet_schema(path).equals(
            SUBMISSION_METADATA_SCHEMA, check_metadata=False
        )
    except (pa.ArrowInvalid, OSError, ValueError):
        return False


def inspect_chunk(
    chunk_id: int,
    path: Path,
    *,
    expected_ciks: tuple[str, ...] | None = None,
    expected_fingerprint: str | None = None,
) -> ChunkInfo | None:
    """Validate one chunk checkpoint, returning ``None`` when unusable."""
    if not path.is_file():
        return None
    if not schema_matches(path):
        return None

    try:
        row_count = count_parquet_rows(path)
    except (pa.ArrowInvalid, OSError, ValueError):
        return None

    ciks: tuple[str, ...] = ()
    if expected_ciks is not None:
        table = _read_columns(path, ("cik", "input_fingerprint"))
        if table is None:
            return None
        ciks = tuple(str(value) for value in table.column("cik").to_pylist())
        if expected_ciks and (
            len(ciks) != len(expected_ciks) or set(ciks) != set(expected_ciks)
        ):
            return None
        if expected_fingerprint:
            fingerprints = {
                value
                for value in table.column("input_fingerprint").to_pylist()
                if value
            }
            if fingerprints - {expected_fingerprint}:
                return None
    elif row_count == 0:
        return None

    return ChunkInfo(
        chunk_id=chunk_id,
        path=path,
        row_count=row_count,
        ciks=ciks,
        file_sha256=file_sha256(path),
    )


def _read_columns(path: Path, columns: tuple[str, ...]) -> pa.Table | None:
    from edgar_sec.infra.storage.parquet import read_parquet_table

    try:
        return read_parquet_table(path, columns=list(columns))
    except (pa.ArrowInvalid, OSError, ValueError, KeyError):
        return None


def discover_completed_chunks(
    plan: dict,
    run_paths: RunPaths,
) -> dict[int, ChunkInfo]:
    """Return every valid chunk checkpoint for a plan, keyed by chunk id."""
    expected_by_id = {
        int(chunk["chunk_id"]): tuple(chunk["cik_padded"])
        for chunk in plan.get("chunks", [])
    }
    fingerprint = plan.get("input_fingerprint")
    completed: dict[int, ChunkInfo] = {}
    for chunk_id, expected_ciks in expected_by_id.items():
        info = inspect_chunk(
            chunk_id,
            run_paths.chunk_file(chunk_id),
            expected_ciks=expected_ciks,
            expected_fingerprint=fingerprint if isinstance(fingerprint, str) else None,
        )
        if info is not None:
            completed[chunk_id] = info
    return completed
