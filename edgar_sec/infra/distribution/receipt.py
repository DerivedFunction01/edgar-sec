"""Cryptographic worker receipts and digest verification."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.atomic import atomic_write_json

from .protocol import WorkerReceipt

RECEIPT_FILE_NAME = "receipt.json"


def build_worker_receipt(
    pipeline: str,
    plan_id: str,
    worker_id: str,
    completed_chunks: Sequence[int],
    row_count: int,
    chunk_files: Sequence[Path] | Mapping[int, Path],
    bundle_root: Path,
) -> WorkerReceipt:
    """Build a cryptographic worker receipt hashing all produced chunks."""
    digests: dict[str, str] = {}
    files = chunk_files.values() if isinstance(chunk_files, Mapping) else chunk_files

    for f in files:
        if not f.is_file():
            continue
        rel = f.relative_to(bundle_root).as_posix()
        digests[rel] = file_sha256(f)

    return WorkerReceipt(
        pipeline=pipeline,
        plan_id=plan_id,
        worker_id=worker_id,
        completed_chunks=tuple(sorted(set(completed_chunks))),
        row_count=row_count,
        digests=digests,
    )


def write_receipt(receipt: WorkerReceipt, destination: Path) -> Path:
    """Persist signed worker receipt atomically."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "pipeline": receipt.pipeline,
        "plan_id": receipt.plan_id,
        "worker_id": receipt.worker_id,
        "completed_chunks": list(receipt.completed_chunks),
        "row_count": receipt.row_count,
        "digests": receipt.digests,
    }
    atomic_write_json(destination, payload)
    return destination


def read_receipt(source: Path) -> WorkerReceipt:
    """Read and validate a signed worker receipt."""
    if not source.is_file():
        raise ValueError(f"receipt file does not exist: {source}")
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"receipt unreadable: {source}") from exc

    required = (
        "pipeline",
        "plan_id",
        "worker_id",
        "completed_chunks",
        "row_count",
        "digests",
    )
    for key in required:
        if key not in data:
            raise ValueError(f"receipt missing required field {key!r}: {source}")

    return WorkerReceipt(
        pipeline=str(data["pipeline"]),
        plan_id=str(data["plan_id"]),
        worker_id=str(data["worker_id"]),
        completed_chunks=tuple(data["completed_chunks"]),
        row_count=int(data["row_count"]),
        digests=dict(data["digests"]),
    )


def verify_receipt_digests(
    receipt: WorkerReceipt, bundle_root: Path
) -> tuple[bool, str]:
    """Verify that every chunk recorded in the receipt matches its on-disk SHA256."""
    for rel_path, expected_hash in receipt.digests.items():
        chunk_path = bundle_root / rel_path
        if not chunk_path.is_file():
            return False, f"missing chunk file: {rel_path}"
        actual_hash = file_sha256(chunk_path)
        if actual_hash != expected_hash:
            return (
                False,
                f"digest mismatch for {rel_path}: expected {expected_hash}, got {actual_hash}",
            )
    return True, ""
