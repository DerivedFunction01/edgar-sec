"""Static chunk-to-worker assignment.

An assignment answers "which machine runs which chunks" and nothing else. It is a
separate, content-addressed artifact rather than a field of the plan, which is
the whole reason reassigning workers is free: the plan id, the plan directory,
and every completed checkpoint stay exactly where they were.

There is no scheduler here and no lease. A worker is told its chunk list, runs
it, and produces a receipt. Deciding that is insufficient is a deliberate
boundary, not an oversight.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa

from edgar_sec.foundation.hashing import file_sha256, sha256_bytes
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.infra.storage.parquet import read_parquet_schema, write_parquet_table

from .paths import RunPaths

ASSIGNMENT_SCHEMA_VERSION = "1.0.0"
RECEIPT_SCHEMA_VERSION = "1.0.0"

_ASSIGNMENT_ID_PREFIX = "chunk-assignment-v1"
_RECEIPT_ID_PREFIX = "chunk-receipt-v1"

__all__ = [
    "ASSIGNMENT_SCHEMA_VERSION",
    "RECEIPT_SCHEMA_VERSION",
    "Assignment",
    "AssignmentError",
    "ChunkReceipt",
    "ChunkResultRecord",
    "build_assignment",
    "build_receipt",
    "divide_chunks",
    "finalize_receipt",
    "read_assignment",
    "read_receipt",
    "write_assignment",
    "write_receipt",
]

ASSIGNMENT_SCHEMA = pa.schema(
    [
        ("assignment_id", pa.string()),
        ("plan_id", pa.string()),
        ("worker_id", pa.string()),
        ("chunk_id", pa.int64()),
    ]
)


class AssignmentError(ValueError):
    """Raised when an assignment or receipt cannot be produced or trusted."""


def derive_assignment_id(plan_id: str, worker_id: str, chunk_ids: list[int]) -> str:
    """Content-derived identity for one chunk-to-worker mapping.

    Derived from the plan it belongs to, so two assignments of the same chunk
    list to different workers are different artifacts while a re-derived mapping
    of the same list is byte-identical across machines. The chunk list is sorted
    before hashing: an assignment is a *set* of chunks, and the order a worker
    happens to enumerate them in is not a property of the work.
    """
    ordered = sorted(set(chunk_ids))
    if not ordered:
        raise AssignmentError(f"assignment for worker {worker_id!r} covers no chunks")
    material = ":".join(
        (
            _ASSIGNMENT_ID_PREFIX,
            ASSIGNMENT_SCHEMA_VERSION,
            plan_id,
            worker_id,
            ",".join(str(chunk_id) for chunk_id in ordered),
        )
    )
    return sha256_bytes(material.encode("utf-8"))[:16]


def divide_chunks(chunk_count: int, worker_count: int) -> dict[str, list[int]]:
    """Split chunk ids round-robin across named workers.

    Round-robin over chunks rather than contiguous blocks so every worker gets a
    comparable share regardless of where a run was interrupted. The mapping is
    deterministic, so the same request on two machines produces the same bundles.
    """
    if worker_count < 1:
        raise ValueError(f"worker_count must be >= 1, got {worker_count}")
    if chunk_count < 1:
        raise ValueError(f"chunk_count must be >= 1, got {chunk_count}")
    workers = [f"worker-{index:02d}" for index in range(worker_count)]
    return {
        worker: [
            chunk_id
            for chunk_id in range(chunk_count)
            if chunk_id % worker_count == index
        ]
        for index, worker in enumerate(workers)
    }


@dataclass(frozen=True, slots=True)
class Assignment:
    """One immutable chunk-to-worker mapping for one plan."""

    assignment_id: str
    plan_id: str
    worker_id: str
    chunk_ids: tuple[int, ...]

    def to_rows(self) -> list[dict[str, object]]:
        """Flat rows for the assignment dataset."""
        return [
            {
                "assignment_id": self.assignment_id,
                "plan_id": self.plan_id,
                "worker_id": self.worker_id,
                "chunk_id": chunk_id,
            }
            for chunk_id in self.chunk_ids
        ]


def build_assignment(plan_id: str, worker_id: str, chunk_ids: list[int]) -> Assignment:
    """Build one assignment for a worker over an explicit chunk list."""
    ordered = sorted(set(chunk_ids))
    return Assignment(
        assignment_id=derive_assignment_id(plan_id, worker_id, ordered),
        plan_id=plan_id,
        worker_id=worker_id,
        chunk_ids=tuple(ordered),
    )


def write_assignment(assignment: Assignment, run_paths: RunPaths) -> str:
    """Write one assignment dataset atomically; return its SHA-256 digest."""
    path = run_paths.assignment_file(assignment.assignment_id)
    table = pa.Table.from_pylist(assignment.to_rows(), schema=ASSIGNMENT_SCHEMA)
    write_parquet_table(table, path)
    if not read_parquet_schema(path).equals(ASSIGNMENT_SCHEMA, check_metadata=False):
        raise AssignmentError(f"assignment dataset schema drifted: {path}")
    return file_sha256(path)


def read_assignment(path: str | os.PathLike[str]) -> Assignment:
    """Load one assignment dataset and re-derive its identity."""
    import pyarrow.parquet as pq

    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(f"assignment not found: {target}")
    if not read_parquet_schema(target).equals(ASSIGNMENT_SCHEMA, check_metadata=False):
        raise AssignmentError(f"assignment dataset schema drifted: {target}")
    table = pq.read_table(target)
    rows = table.to_pylist()
    if not rows:
        raise AssignmentError(f"assignment covers no chunks: {target}")
    plan_ids = {str(row["plan_id"]) for row in rows}
    workers = {str(row["worker_id"]) for row in rows}
    ids = {str(row["assignment_id"]) for row in rows}
    if len(plan_ids) != 1 or len(workers) != 1 or len(ids) != 1:
        raise AssignmentError(
            f"assignment mixes plan/worker/identity values: {sorted(ids)}"
        )
    chunk_ids = sorted(int(row["chunk_id"]) for row in rows)
    expected = derive_assignment_id(
        next(iter(plan_ids)), next(iter(workers)), chunk_ids
    )
    if next(iter(ids)) != expected:
        raise AssignmentError(
            f"assignment at {target} claims identity {next(iter(ids))!r}, "
            f"its contents derive {expected!r}"
        )
    return Assignment(
        assignment_id=expected,
        plan_id=next(iter(plan_ids)),
        worker_id=next(iter(workers)),
        chunk_ids=tuple(chunk_ids),
    )


@dataclass(frozen=True, slots=True)
class ChunkResultRecord:
    """One completed chunk file as the worker measured it.

    ``relative_path`` is the worker's path relative to the root of the returned
    bundle, so a coordinator resolves it against whatever directory the bundle
    arrived in rather than assuming a layout.
    """

    chunk_id: int
    relative_path: str
    row_count: int
    file_sha256: str

    def to_row(self) -> dict[str, object]:
        """Flat row for the receipt's chunk list."""
        return {
            "chunk_id": self.chunk_id,
            "relative_path": self.relative_path,
            "row_count": self.row_count,
            "file_sha256": self.file_sha256,
        }


@dataclass(frozen=True, slots=True)
class ChunkReceipt:
    """What one worker produced, and what it believes about each file.

    The receipt is the only thing that crosses the machine boundary, so it
    carries enough to refuse a forged or mismatched chunk: the plan and
    assignment it was produced under, the worker, and a digest per file.
    """

    plan_id: str
    assignment_id: str
    worker_id: str
    chunks: tuple[ChunkResultRecord, ...]
    row_count: int = 0
    file_sha256: str = ""
    completed_at: str = ""

    def chunk_ids(self) -> list[int]:
        """Chunk ids this receipt covers."""
        return [record.chunk_id for record in self.chunks]

    def to_manifest(self) -> dict[str, object]:
        """Serialize the receipt for the machine boundary."""
        return {
            "receipt_schema_version": RECEIPT_SCHEMA_VERSION,
            "plan_id": self.plan_id,
            "assignment_id": self.assignment_id,
            "worker_id": self.worker_id,
            "row_count": self.row_count,
            "file_sha256": self.file_sha256,
            "completed_at": self.completed_at,
            "chunks": [record.to_row() for record in self.chunks],
        }


def build_receipt(
    *,
    plan_id: str,
    assignment: Assignment,
    chunks: list[ChunkResultRecord],
    completed_at: str = "",
) -> ChunkReceipt:
    """Build a worker receipt from the chunk files it produced."""
    return ChunkReceipt(
        plan_id=plan_id,
        assignment_id=assignment.assignment_id,
        worker_id=assignment.worker_id,
        chunks=tuple(sorted(chunks, key=lambda record: record.chunk_id)),
        row_count=sum(record.row_count for record in chunks),
        completed_at=completed_at,
    )


def write_receipt(receipt: ChunkReceipt, path: Path) -> Path:
    """Write a worker's receipt at the root of the directory it hands back."""
    atomic_write_json(path, receipt.to_manifest(), canonical=False, indent=2)
    return path


def read_receipt(path: str | os.PathLike[str]) -> ChunkReceipt:
    """Load a receipt and verify its declared digest against its own content.

    The digest covers the chunk list, so a receipt edited to add or drop a chunk
    is detectable before any file is copied or trusted.
    """
    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(f"receipt not found: {target}")
    manifest = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise AssignmentError(f"receipt is not a JSON object: {target}")
    if manifest.get("receipt_schema_version") != RECEIPT_SCHEMA_VERSION:
        raise AssignmentError(
            f"receipt at {target} is version {manifest.get('receipt_schema_version')!r}, "
            f"this build requires {RECEIPT_SCHEMA_VERSION!r}"
        )
    chunks = tuple(
        ChunkResultRecord(
            chunk_id=int(row["chunk_id"]),
            relative_path=str(row["relative_path"]),
            row_count=int(row["row_count"]),
            file_sha256=str(row["file_sha256"]),
        )
        for row in manifest.get("chunks", [])
    )
    receipt = ChunkReceipt(
        plan_id=str(manifest.get("plan_id", "")),
        assignment_id=str(manifest.get("assignment_id", "")),
        worker_id=str(manifest.get("worker_id", "")),
        chunks=chunks,
        row_count=int(manifest.get("row_count", 0)),
        file_sha256=str(manifest.get("file_sha256", "")),
        completed_at=str(manifest.get("completed_at", "")),
    )
    expected = _receipt_digest(receipt)
    if receipt.file_sha256 != expected:
        raise AssignmentError(
            f"receipt at {target} declares digest {receipt.file_sha256!r}, "
            f"its contents derive {expected!r}"
        )
    return receipt


def _receipt_digest(receipt: ChunkReceipt) -> str:
    """Digest over the receipt's identifying content, excluding its own digest."""
    material = ":".join(
        (
            _RECEIPT_ID_PREFIX,
            RECEIPT_SCHEMA_VERSION,
            receipt.plan_id,
            receipt.assignment_id,
            receipt.worker_id,
            ";".join(
                f"{record.chunk_id},{record.relative_path},{record.row_count},"
                f"{record.file_sha256}"
                for record in receipt.chunks
            ),
        )
    )
    return sha256_bytes(material.encode("utf-8"))[:32]


def finalize_receipt(receipt: ChunkReceipt, completed_at: str) -> ChunkReceipt:
    """Stamp a receipt with its derived digest and completion time."""
    stamped = ChunkReceipt(
        plan_id=receipt.plan_id,
        assignment_id=receipt.assignment_id,
        worker_id=receipt.worker_id,
        chunks=receipt.chunks,
        row_count=receipt.row_count,
        completed_at=completed_at or receipt.completed_at,
    )
    return ChunkReceipt(
        plan_id=stamped.plan_id,
        assignment_id=stamped.assignment_id,
        worker_id=stamped.worker_id,
        chunks=stamped.chunks,
        row_count=stamped.row_count,
        file_sha256=_receipt_digest(stamped),
        completed_at=stamped.completed_at,
    )
