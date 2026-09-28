"""Unit tests for foundation.hashing."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.foundation.hashing import file_sha256, sha256_bytes

HELLO_SHA256 = "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"


def test_file_sha256_matches_known_digest(tmp_path: Path) -> None:
    path = tmp_path / "hello.txt"
    path.write_text("hello world", encoding="utf-8")
    assert file_sha256(path) == HELLO_SHA256


def test_sha256_bytes_agrees_with_file_sha256(tmp_path: Path) -> None:
    path = tmp_path / "hello.txt"
    path.write_text("hello world", encoding="utf-8")
    assert sha256_bytes(b"hello world") == file_sha256(path)


def test_file_sha256_streams_large_files(tmp_path: Path) -> None:
    path = tmp_path / "large.bin"
    payload = b"z" * (1024 * 1024 + 17)
    path.write_bytes(payload)
    assert file_sha256(path) == sha256_bytes(payload)
