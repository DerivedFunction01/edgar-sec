"""Atomic Parquet checkpoint writes and completed-chunk discovery.

Checkpoint files are append-safe immutable artifacts: a completed chunk is
written to a temporary path, validated against the declared schema, then
atomically renamed into place. Interrupted work may leave ``.tmp`` partials,
which are ignored on resume.
"""

from __future__ import annotations

import os
import re

import pyarrow as pa
import pyarrow.parquet as pq

from .schemas import (
    DATASET_NAME,
    SCHEMA_VERSION,
    SUBMISSION_METADATA_SCHEMA,
    TERMINAL_STATUSES,
)

CHUNK_FILE_RE = re.compile(
    rf"^{DATASET_NAME}-v(?P<version>[A-Za-z0-9.]+)-chunk-(?P<chunk_id>\d+)-"
    r"(?P<start>\d+)-(?P<end>\d+)\.parquet$"
)


def chunk_filename(chunk_id: int, start_row: int, end_row: int) -> str:
    """File names include dataset version, chunk id, and row range."""
    return f"{DATASET_NAME}-v{SCHEMA_VERSION}-chunk-{chunk_id:05d}-{start_row:06d}-{end_row:06d}.parquet"


def parse_chunk_filename(name: str) -> dict | None:
    match = CHUNK_FILE_RE.match(os.path.basename(name))
    if not match:
        return None
    return {
        "version": match.group("version"),
        "chunk_id": int(match.group("chunk_id")),
        "start_row": int(match.group("start")),
        "end_row": int(match.group("end")),
    }


def write_checkpoint(rows: list[dict], final_path: str) -> dict:
    """Atomically write a validated chunk checkpoint. Returns metadata about
    the written file."""
    if not rows:
        raise ValueError("refusing to write an empty checkpoint")
    table = pa.Table.from_pylist(rows, schema=SUBMISSION_METADATA_SCHEMA)
    final_path = os.path.abspath(final_path)
    os.makedirs(os.path.dirname(final_path), exist_ok=True)
    tmp_path = final_path + ".tmp"
    pq.write_table(table, tmp_path)

    # Validate the temporary artifact before making it visible.
    written = pq.read_table(tmp_path, schema=SUBMISSION_METADATA_SCHEMA)
    if written.num_rows != len(rows):
        os.remove(tmp_path)
        raise ValueError(
            f"checkpoint validation failed: wrote {len(rows)} rows, read back {written.num_rows}"
        )
    if str(written.schema) != str(SUBMISSION_METADATA_SCHEMA):
        os.remove(tmp_path)
        raise ValueError("checkpoint validation failed: schema drift detected")
    os.replace(tmp_path, final_path)
    return {
        "path": final_path,
        "rows": written.num_rows,
        "bytes": os.path.getsize(final_path),
        "schema_version": SCHEMA_VERSION,
    }


def load_checkpoint(path: str, expected_version: str | None = None) -> pa.Table | None:
    """Load a completed checkpoint, or None when it does not exist or is
    still a temporary partial. Schema/version mismatches raise."""
    if not os.path.exists(path) or path.endswith(".tmp"):
        return None
    table = pq.read_table(path, schema=SUBMISSION_METADATA_SCHEMA)
    if expected_version is not None:
        versions = table.column("schema_version").unique().to_pylist()
        if versions != [expected_version]:
            raise ValueError(f"checkpoint {path} has schema versions {versions}, expected {expected_version}")
    return table


def find_chunk_checkpoint(chunks_dir: str, chunk_id: int, expected_version: str | None = None) -> str | None:
    """Return the checkpoint path for a chunk if a valid completed file
    exists with matching versions; otherwise None."""
    if not os.path.isdir(chunks_dir):
        return None
    for name in sorted(os.listdir(chunks_dir)):
        info = parse_chunk_filename(name)
        if not info or info["chunk_id"] != chunk_id:
            continue
        if expected_version is not None and info["version"] != expected_version:
            continue
        path = os.path.join(chunks_dir, name)
        table = load_checkpoint(path, expected_version)
        if table is not None and table.num_rows > 0:
            return path
    return None


def list_chunk_checkpoints(chunks_dir: str) -> list[dict]:
    """List completed chunk checkpoints with parsed metadata."""
    out = []
    if not os.path.isdir(chunks_dir):
        return out
    for name in sorted(os.listdir(chunks_dir)):
        info = parse_chunk_filename(name)
        if info:
            out.append({**info, "path": os.path.join(chunks_dir, name)})
    return out


def summarize_checkpoints(chunks_dir: str) -> dict:
    """Aggregate statuses across completed checkpoints for `status`."""
    from collections import Counter

    status_counts: Counter = Counter()
    rows_total = 0
    ciks: list[str] = []
    filings_total = 0
    historical_failures = 0
    retryable_errors = 0
    files = list_chunk_checkpoints(chunks_dir)
    for info in files:
        table = load_checkpoint(info["path"])
        if table is None:
            continue
        rows_total += table.num_rows
        ciks.extend(table.column("cik").to_pylist())
        status_counts.update(table.column("status").to_pylist())
        filings_total += sum(
            len(value or []) for value in table.column("filings").to_pylist()
        )
        historical_failures += sum(
            value or 0 for value in table.column("historical_files_failed").to_pylist()
        )
        retryable_errors += sum(
            1
            for value in table.column("status").to_pylist()
            if value not in TERMINAL_STATUSES
        )
    return {
        "chunk_files": len(files),
        "rows_total": rows_total,
        "unique_ciks": len(set(ciks)),
        "status_counts": dict(status_counts),
        "filings_total": filings_total,
        "historical_file_failures": historical_failures,
        "non_terminal_rows": retryable_errors,
        "mergeable": rows_total > 0 and retryable_errors == 0,
    }
