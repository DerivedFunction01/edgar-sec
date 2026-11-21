"""Tests for cryptographic worker receipts and digest verification."""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.infra.distribution.receipt import (
    RECEIPT_FILE,
    build_worker_receipt,
    read_receipt,
    verify_receipt_digests,
    write_receipt,
)


def test_receipt_build_write_read(tmp_path: Path) -> None:
    """Verifies receipt hashing and serialization round-trip."""
    chunk = tmp_path / "chunks" / "chunk-0.parquet"
    chunk.parent.mkdir(parents=True)
    chunk.write_bytes(b"mock-chunk-content")

    receipt = build_worker_receipt(
        "meta",
        "work-1",
        "d" * 64,
        "assignment",
        "w1",
        (0,),
        [chunk],
        tmp_path,
        {"row_count": 100},
    )
    dest = tmp_path / RECEIPT_FILE
    write_receipt(receipt, dest)

    loaded = read_receipt(dest)
    assert loaded.pipeline == "meta"
    assert loaded.work_id == "work-1"
    assert loaded.worker_id == "w1"
    assert loaded.completed_chunks == (0,)
    assert loaded.result_metadata["row_count"] == 100
    assert "chunks/chunk-0.parquet" in loaded.file_records
    assert loaded.file_records["chunks/chunk-0.parquet"].size_bytes == len(
        b"mock-chunk-content"
    )


def test_verify_receipt_digests(tmp_path: Path) -> None:
    """Verifies digest validation succeeds and detects tampering."""
    chunk = tmp_path / "part.parquet"
    chunk.write_bytes(b"original")

    receipt = build_worker_receipt(
        "meta", "work-1", "d" * 64, "assignment", "w1", (0,), [chunk], tmp_path
    )
    valid, err = verify_receipt_digests(receipt, tmp_path)
    assert valid and not err

    chunk.write_bytes(b"tampered")
    invalid, err = verify_receipt_digests(receipt, tmp_path)
    assert not invalid
    assert "digest mismatch" in err


def test_unsupported_receipt_schema_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / RECEIPT_FILE
    source.write_text(
        '{"schema_version": 99}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unsupported receipt schema"):
        read_receipt(source)


def test_receipt_detects_size_and_path_tampering(tmp_path: Path) -> None:
    output = tmp_path / "output.bin"
    output.write_bytes(b"original")
    receipt = build_worker_receipt(
        "inventory",
        "run-1",
        "d" * 64,
        "assignment",
        "worker-00",
        (0,),
        [output],
        tmp_path,
    )
    output.write_bytes(b"short")
    valid, error = verify_receipt_digests(receipt, tmp_path)
    assert not valid
    assert error == "size mismatch for output.bin"
