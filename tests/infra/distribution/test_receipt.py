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

    receipt = build_worker_receipt("meta", "p1", "w1", (0,), 100, [chunk], tmp_path)
    dest = tmp_path / RECEIPT_FILE
    write_receipt(receipt, dest)

    loaded = read_receipt(dest)
    assert loaded.pipeline == "meta"
    assert loaded.plan_id == "p1"
    assert loaded.worker_id == "w1"
    assert loaded.completed_chunks == (0,)
    assert loaded.row_count == 100
    assert "chunks/chunk-0.parquet" in loaded.digests


def test_verify_receipt_digests(tmp_path: Path) -> None:
    """Verifies digest validation succeeds and detects tampering."""
    chunk = tmp_path / "part.parquet"
    chunk.write_bytes(b"original")

    receipt = build_worker_receipt("meta", "p1", "w1", (0,), 5, [chunk], tmp_path)
    valid, err = verify_receipt_digests(receipt, tmp_path)
    assert valid and not err

    chunk.write_bytes(b"tampered")
    invalid, err = verify_receipt_digests(receipt, tmp_path)
    assert not invalid
    assert "digest mismatch" in err
