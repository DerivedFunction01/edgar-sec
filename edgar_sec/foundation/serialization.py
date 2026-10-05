"""Deterministic in-memory serialization primitives.

:func:`canonical_json` guarantees *reproducibility* -- one input, one byte string --
so a digest is meaningful. :func:`json_safe` guarantees only *representability* and is
lossy by design; using it where canonical JSON belongs destroys that property.
"""

from __future__ import annotations

import base64
import datetime
import decimal
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any


def canonical_json(data: Any) -> str:
    """Deterministic JSON serialization with sorted keys and compact separators."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def canonical_hash(data: Any) -> str:
    """Compute SHA-256 hex digest of canonical JSON-serialized data."""
    encoded = canonical_json(data).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def json_safe(value: Any) -> Any:
    """Coerce a value into something ``json.dumps`` can encode without error.

    A bare ``NaN``/``Infinity`` becomes ``None`` (a strict parser would reject the whole
    document) and a ``Decimal`` becomes its exact string -- never a guessed float.
    """
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if isinstance(value, datetime.datetime | datetime.date | datetime.time):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence):
        return [json_safe(item) for item in value]
    return str(value)


def safe_dumps(value: Any) -> str:
    """``json.dumps`` with viewer-style normalization applied first."""
    return json.dumps(json_safe(value), default=str)


__all__ = ["canonical_hash", "canonical_json", "json_safe", "safe_dumps"]
