"""Worker receipt serialization and output-file verification."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from edgar_sec.foundation.hashing import file_sha256, is_sha256_hex_digest
from edgar_sec.infra.storage.atomic import atomic_write_json

from .protocol import WorkerFile, WorkerReceipt

RECEIPT_FILE = "receipt.json"
RECEIPT_SCHEMA_VERSION = 2


def build_worker_receipt(
    pipeline: str,
    work_id: str,
    work_digest: str,
    assignment_id: str,
    worker_id: str,
    completed_chunks: Sequence[int],
    output_files: Sequence[Path] | Mapping[int, Path],
    bundle_root: Path,
    result_metadata: Mapping[str, Any] | None = None,
) -> WorkerReceipt:
    root = bundle_root.resolve()
    file_records: dict[str, WorkerFile] = {}
    files = output_files.values() if isinstance(output_files, Mapping) else output_files
    for output in files:
        if not output.is_file():
            continue
        path = output.resolve()
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError as exc:
            raise ValueError(f"receipt output is outside its bundle: {output}") from exc
        if relative in file_records:
            raise ValueError(f"receipt output is duplicated: {relative}")
        file_records[relative] = WorkerFile(
            size_bytes=path.stat().st_size,
            sha256=file_sha256(path),
        )

    return WorkerReceipt(
        pipeline=pipeline,
        work_id=work_id,
        work_digest=work_digest,
        assignment_id=assignment_id,
        worker_id=worker_id,
        completed_chunks=tuple(sorted(set(completed_chunks))),
        file_records=file_records,
        result_metadata=dict(result_metadata or {}),
    )


def write_receipt(receipt: WorkerReceipt, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "pipeline": receipt.pipeline,
        "work_id": receipt.work_id,
        "work_digest": receipt.work_digest,
        "assignment_id": receipt.assignment_id,
        "worker_id": receipt.worker_id,
        "completed_chunks": list(receipt.completed_chunks),
        "file_records": {
            path: {"size_bytes": record.size_bytes, "sha256": record.sha256}
            for path, record in receipt.file_records.items()
        },
        "result_metadata": receipt.result_metadata,
    }
    atomic_write_json(destination, payload)
    return destination


def read_receipt(source: Path) -> WorkerReceipt:
    if not source.is_file():
        raise ValueError(f"receipt file does not exist: {source}")
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"receipt unreadable: {source}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"receipt malformed: {source}")
    if data.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported receipt schema version: {data.get('schema_version')!r}"
        )

    required = (
        "pipeline",
        "work_id",
        "work_digest",
        "assignment_id",
        "worker_id",
        "completed_chunks",
        "file_records",
        "result_metadata",
    )
    for field in required:
        if field not in data:
            raise ValueError(f"receipt missing required field {field!r}: {source}")
    for field in ("pipeline", "work_id", "work_digest", "assignment_id", "worker_id"):
        if not isinstance(data[field], str) or not data[field]:
            raise ValueError(f"receipt has invalid {field}: {source}")
    if not is_sha256_hex_digest(data["work_digest"]):
        raise ValueError(f"receipt has invalid work_digest: {source}")
    completed_chunks = data["completed_chunks"]
    if (
        not isinstance(completed_chunks, list)
        or any(type(value) is not int or value < 0 for value in completed_chunks)
        or len(set(completed_chunks)) != len(completed_chunks)
    ):
        raise ValueError(f"receipt has invalid completed_chunks: {source}")
    raw_files = data["file_records"]
    if not isinstance(raw_files, dict):
        raise ValueError(f"receipt file_records must be an object: {source}")
    records: dict[str, WorkerFile] = {}
    for path, raw in raw_files.items():
        if not isinstance(path, str) or not isinstance(raw, dict):
            raise ValueError(f"receipt has malformed file record: {source}")
        if type(raw.get("size_bytes")) is not int or raw["size_bytes"] < 0:
            raise ValueError(f"receipt has invalid file size: {path}")
        if not is_sha256_hex_digest(raw.get("sha256")):
            raise ValueError(f"receipt has invalid file digest: {path}")
        records[path] = WorkerFile(raw["size_bytes"], raw["sha256"])
    if not isinstance(data["result_metadata"], dict):
        raise ValueError(f"receipt result_metadata must be an object: {source}")
    return WorkerReceipt(
        pipeline=data["pipeline"],
        work_id=data["work_id"],
        work_digest=data["work_digest"],
        assignment_id=data["assignment_id"],
        worker_id=data["worker_id"],
        completed_chunks=tuple(completed_chunks),
        file_records=records,
        result_metadata=data["result_metadata"],
    )


def verify_receipt_digests(
    receipt: WorkerReceipt, bundle_root: Path
) -> tuple[bool, str]:
    root = bundle_root.resolve()
    for relative_path, record in receipt.file_records.items():
        candidate = root / relative_path
        try:
            path = candidate.resolve(strict=True)
            path.relative_to(root)
        except (OSError, ValueError):
            return False, f"missing or unsafe output file: {relative_path}"
        if not path.is_file():
            return False, f"missing output file: {relative_path}"
        if path.stat().st_size != record.size_bytes:
            return False, f"size mismatch for {relative_path}"
        actual_hash = file_sha256(path)
        if actual_hash != record.sha256:
            return False, f"digest mismatch for {relative_path}"
    return True, ""
