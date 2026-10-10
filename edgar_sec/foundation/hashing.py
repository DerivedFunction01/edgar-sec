"""Cryptographic hashing primitives for files and payloads."""

from __future__ import annotations

import hashlib
import os

from edgar_sec.foundation.io import DEFAULT_IO_CHUNK_SIZE

#: Encoding-slice size for :func:`sha256_text`; about a megabyte of ASCII, so a whole
#: filing is hashed without ever holding a second full-size bytes copy.
_TEXT_CHUNK_CHARS = 1 << 20


def file_sha256(path: str | os.PathLike[str]) -> str:
    """Compute SHA-256 hex digest of a file in streaming 64KB blocks."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(DEFAULT_IO_CHUNK_SIZE):
            hasher.update(chunk)
    return hasher.hexdigest()


def sha256_bytes(data: bytes) -> str:
    """Compute SHA-256 hex digest of raw binary bytes."""
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    """Hash a string without holding a second full-size bytes copy.

    Python ``str`` indices are code points and UTF-8 encodes each independently, so
    bounded slices concatenate to exactly the whole string's bytes.
    """
    if len(text) <= _TEXT_CHUNK_CHARS:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    digest = hashlib.sha256()
    for offset in range(0, len(text), _TEXT_CHUNK_CHARS):
        digest.update(text[offset : offset + _TEXT_CHUNK_CHARS].encode("utf-8"))
    return digest.hexdigest()


def is_sha256_hex_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = ["file_sha256", "is_sha256_hex_digest", "sha256_bytes", "sha256_text"]
