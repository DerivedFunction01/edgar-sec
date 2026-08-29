"""Deterministic CIK chunk ranges and run-plan validation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class ChunkRange:
    chunk_id: int
    start_row: int  # inclusive, 0-based row into the ordered CIK list
    end_row: int  # inclusive
    first_cik: str
    last_cik: str

    @property
    def row_count(self) -> int:
        return self.end_row - self.start_row + 1

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "start_row": self.start_row,
            "end_row": self.end_row,
            "first_cik": self.first_cik,
            "last_cik": self.last_cik,
            "row_count": self.row_count,
        }


class ChunkMismatchError(Exception):
    pass


@dataclass(frozen=True)
class PartitionSpec:
    partition_id: int
    partition_count: int
    assignment: str
    cik_padded: tuple[str, ...]
    chunks: tuple[ChunkRange, ...]

    @property
    def row_count(self) -> int:
        return len(self.cik_padded)

    def to_dict(self) -> dict:
        return {
            "partition_id": self.partition_id,
            "partition_count": self.partition_count,
            "assignment": self.assignment,
            "cik_padded": list(self.cik_padded),
            "row_count": self.row_count,
            "chunks": [chunk.to_dict() for chunk in self.chunks],
        }


def assign_partitions(
    cik_padded_list: list[str], partition_count: int, chunk_size: int
) -> list[PartitionSpec]:
    """Assign sorted CIKs using stable round-robin, then chunk each partition."""
    if partition_count < 1:
        raise ValueError("partition_count must be >= 1")
    if chunk_size < 1:
        raise ValueError("chunk_size must be >= 1")
    partitions = []
    for partition_id in range(1, partition_count + 1):
        partition_ciks = tuple(cik_padded_list[partition_id - 1 :: partition_count])
        partitions.append(
            PartitionSpec(
                partition_id=partition_id,
                partition_count=partition_count,
                assignment="round_robin_v1",
                cik_padded=partition_ciks,
                chunks=tuple(assign_chunks(list(partition_ciks), chunk_size)),
            )
        )
    return partitions


def assign_chunks(cik_padded_list: list[str], chunk_size: int) -> list[ChunkRange]:
    """Assign contiguous inclusive ranges over the deterministically ordered
    CIK list. Overlapping or missing coverage is impossible by construction,
    and the assignment is stable for a given input order."""
    if chunk_size < 1:
        raise ValueError("chunk_size must be >= 1")
    chunks: list[ChunkRange] = []
    for chunk_id, start in enumerate(
        range(0, len(cik_padded_list), chunk_size), start=1
    ):
        end = min(start + chunk_size, len(cik_padded_list)) - 1
        chunks.append(
            ChunkRange(
                chunk_id=chunk_id,
                start_row=start,
                end_row=end,
                first_cik=cik_padded_list[start],
                last_cik=cik_padded_list[end],
            )
        )
    return chunks


def plan_hash(plan: dict) -> str:
    """Deterministic hash over the plan content (excluding any previous
    plan_hash field)."""
    from defs.storage import canonical_json

    payload = {key: value for key, value in plan.items() if key != "plan_hash"}
    canonical = canonical_json(payload)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def select_chunk(
    plan: dict, chunk_id: int, input_fingerprint: str, schema_version: str
) -> ChunkRange:
    """Validate a worker's chunk against the plan manifest.

    A worker must reject a chunk whose manifest version (schema), input
    fingerprint, or range does not match its input.
    """
    if plan.get("input_fingerprint") != input_fingerprint:
        raise ChunkMismatchError(
            f"input fingerprint mismatch: plan={plan.get('input_fingerprint')} "
            f"worker={input_fingerprint}"
        )
    if plan.get("schema_version") != schema_version:
        raise ChunkMismatchError(
            f"schema version mismatch: plan={plan.get('schema_version')} worker={schema_version}"
        )
    for chunk in plan.get("chunks", []):
        if chunk.get("chunk_id") == chunk_id:
            return ChunkRange(
                chunk_id=chunk["chunk_id"],
                start_row=chunk["start_row"],
                end_row=chunk["end_row"],
                first_cik=chunk["first_cik"],
                last_cik=chunk["last_cik"],
            )
    known = [chunk.get("chunk_id") for chunk in plan.get("chunks", [])]
    raise ChunkMismatchError(
        f"chunk_id {chunk_id} not present in plan; known chunk ids: {known}"
    )


def chunk_ciks(target_rows: list, chunk: ChunkRange) -> list:
    """Return the target rows assigned to a chunk (inclusive range)."""
    return list(target_rows[chunk.start_row : chunk.end_row + 1])


def verify_chunk_assignment(target_rows: list, chunks: list[ChunkRange]) -> None:
    """Assert the chunk plan covers every row exactly once with no overlaps."""
    expected = 0
    for chunk in chunks:
        if chunk.start_row != expected:
            raise ChunkMismatchError(
                f"chunk {chunk.chunk_id} starts at {chunk.start_row}, expected {expected}"
            )
        if chunk.end_row < chunk.start_row:
            raise ChunkMismatchError(f"chunk {chunk.chunk_id} has an empty range")
        expected = chunk.end_row + 1
    if expected != len(target_rows):
        raise ChunkMismatchError(
            f"chunks cover {expected} rows but the input has {len(target_rows)}"
        )


def find_chunk(plan: dict, chunk_id: int) -> ChunkRange | None:
    for chunk in plan.get("chunks", []):
        if chunk.get("chunk_id") == chunk_id:
            return ChunkRange(
                chunk_id=chunk["chunk_id"],
                start_row=chunk["start_row"],
                end_row=chunk["end_row"],
                first_cik=chunk["first_cik"],
                last_cik=chunk["last_cik"],
            )
    return None
