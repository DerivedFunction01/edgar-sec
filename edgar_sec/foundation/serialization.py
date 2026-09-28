"""Deterministic in-memory serialization primitives."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(data: Any) -> str:
    """Deterministic JSON serialization with sorted keys and compact separators."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def canonical_hash(data: Any) -> str:
    """Compute SHA-256 hex digest of canonical JSON-serialized data."""
    encoded = canonical_json(data).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = ["canonical_hash", "canonical_json"]
