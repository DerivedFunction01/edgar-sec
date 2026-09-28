"""Cryptographic and deterministic serialization primitives."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def file_sha256(path: Path | str) -> str:
    """Compute SHA-256 hex digest of a file in 64KB blocks."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def canonical_json(data: Any) -> str:
    """Deterministic JSON serialization with sorted keys and tight separators."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def canonical_hash(data: Any) -> str:
    """Compute SHA-256 hex digest of canonical JSON-serialized data."""
    encoded = canonical_json(data).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = ["canonical_hash", "canonical_json", "file_sha256"]
