"""Compatibility helpers around the phase 1 storage facade."""

from __future__ import annotations

import os
from collections import Counter

from defs.storage import ChunkRange, DatasetSpec, RunContext, make_chunk_backend

from .schemas import (
    DATASET_NAME,
    SCHEMA_VERSION,
    SUBMISSION_METADATA_SCHEMA,
    TERMINAL_STATUSES,
)
from .storage import Phase1CheckpointStore


def chunk_filename(
    chunk_id: int, start_row: int, end_row: int, storage_format: str = "parquet"
) -> str:
    if storage_format not in {"parquet", "jsonl"}:
        raise ValueError("storage_format must be 'parquet' or 'jsonl'")
    extension = "jsonl" if storage_format == "jsonl" else "parquet"
    return f"{DATASET_NAME}-v{SCHEMA_VERSION}-chunk-{chunk_id:05d}-{start_row:06d}-{end_row:06d}.{extension}"


def _store(root: str, storage_format: str = "parquet") -> Phase1CheckpointStore:
    spec = DatasetSpec(DATASET_NAME, SCHEMA_VERSION, "cik", SUBMISSION_METADATA_SCHEMA)
    backend = make_chunk_backend(storage_format, root)
    return Phase1CheckpointStore(backend, spec=spec, run=RunContext(run_id="compat"))


def write_checkpoint(
    rows: list[dict], final_path: str, storage_format: str = "parquet"
) -> dict:
    if not rows:
        raise ValueError("refusing to write an empty checkpoint")
    parsed = parse_chunk_filename(os.path.basename(final_path), storage_format)
    if parsed is None:
        raise ValueError(f"invalid {storage_format} checkpoint filename: {final_path}")
    ref = _store(os.path.dirname(os.path.dirname(final_path)), storage_format).write(
        rows, ChunkRange(parsed["chunk_id"], parsed["start_row"], parsed["end_row"])
    )
    return {
        "path": ref.path,
        "rows": ref.row_count,
        "bytes": ref.bytes,
        "schema_version": ref.version,
    }


class _Column:
    def __init__(self, values):
        self.values = values

    def to_pylist(self):
        return self.values

    def unique(self):
        return _Column(list(dict.fromkeys(self.values)))


class _RecordTable:
    def __init__(self, rows):
        self.rows = rows
        self.num_rows = len(rows)

    def column(self, name):
        return _Column([row.get(name) for row in self.rows])


def load_checkpoint(path: str, expected_version: str | None = None):
    if not os.path.exists(path) or path.endswith(".tmp"):
        return None
    storage_format = "jsonl" if path.endswith(".jsonl") else "parquet"
    parsed = parse_chunk_filename(os.path.basename(path), storage_format)
    if parsed is None:
        raise ValueError(f"invalid checkpoint filename: {path}")
    store = _store(os.path.dirname(os.path.dirname(path)), storage_format)
    rows = store.load(parsed["chunk_id"])
    if expected_version is not None and any(
        row.get("schema_version") != expected_version for row in rows
    ):
        versions = list(dict.fromkeys(row.get("schema_version") for row in rows))
        raise ValueError(
            f"checkpoint {path} has schema versions {versions}, expected {expected_version}"
        )
    return _RecordTable(rows)


def parse_chunk_filename(name: str, storage_format: str = "parquet") -> dict | None:
    import re

    extension = "jsonl" if storage_format == "jsonl" else "parquet"
    match = re.match(
        rf"^{DATASET_NAME}-v(?P<version>[A-Za-z0-9.]+)-chunk-(?P<chunk_id>\d+)-(?P<start>\d+)-(?P<end>\d+)\.{extension}$",
        os.path.basename(name),
    )
    if not match:
        return None
    return {
        "version": match.group("version"),
        "chunk_id": int(match.group("chunk_id")),
        "start_row": int(match.group("start")),
        "end_row": int(match.group("end")),
    }


def list_chunk_checkpoints(
    chunks_dir: str, storage_format: str = "parquet"
) -> list[dict]:
    root = os.path.dirname(chunks_dir)
    return [
        {
            "version": ref.version,
            "chunk_id": ref.chunk_id,
            "start_row": ref.start_row,
            "end_row": ref.end_row,
            "path": ref.path,
        }
        for ref in _store(root, storage_format).list()
    ]


def find_chunk_checkpoint(
    chunks_dir: str,
    chunk_id: int,
    expected_version: str | None = None,
    storage_format: str = "parquet",
) -> str | None:
    for info in list_chunk_checkpoints(chunks_dir, storage_format):
        if info["chunk_id"] == chunk_id and (
            expected_version is None or info["version"] == expected_version
        ):
            return info["path"]
    return None


def summarize_checkpoints(chunks_dir: str, storage_format: str = "parquet") -> dict:
    status_counts = Counter()
    rows_total = filings_total = historical_failures = retryable_errors = 0
    ciks = []
    infos = list_chunk_checkpoints(chunks_dir, storage_format)
    store = _store(os.path.dirname(chunks_dir), storage_format)
    for info in infos:
        rows = store.load(info["chunk_id"])
        rows_total += len(rows)
        ciks.extend(row["cik"] for row in rows)
        status_counts.update(row["status"] for row in rows)
        filings_total += sum(len(row.get("filings") or []) for row in rows)
        historical_failures += sum(
            row.get("historical_files_failed") or 0 for row in rows
        )
        retryable_errors += sum(row["status"] not in TERMINAL_STATUSES for row in rows)
    return {
        "chunk_files": len(infos),
        "rows_total": rows_total,
        "unique_ciks": len(set(ciks)),
        "status_counts": dict(status_counts),
        "filings_total": filings_total,
        "historical_file_failures": historical_failures,
        "non_terminal_rows": retryable_errors,
        "mergeable": rows_total > 0 and retryable_errors == 0,
    }
