"""Cryptographic hashing primitives for files and payloads."""

from __future__ import annotations

import hashlib
import os


def file_sha256(path: str | os.PathLike[str]) -> str:
    """Compute SHA-256 hex digest of a file in streaming 64KB blocks."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def sha256_bytes(data: bytes) -> str:
    """Compute SHA-256 hex digest of raw binary bytes."""
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    """Compute SHA-256 hex digest of UTF-8 text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


__all__ = ["file_sha256", "sha256_bytes", "sha256_text"]
