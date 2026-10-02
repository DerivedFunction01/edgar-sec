"""Deterministic in-memory serialization primitives.

Two distinct concerns live here, and the difference is worth keeping straight.

:func:`canonical_json` is about *reproducibility* -- one input always produces
one byte string, which is what makes a digest meaningful.

:func:`json_safe` is about *representability* -- converting a value that
``json.dumps`` would reject (or silently mangle) into one it will accept. It is
lossy by design and carries no determinism guarantee. Using it where canonical
JSON belongs would quietly destroy the property the digest depends on.
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

    Query results and checkpoint records carry types the JSON encoder has no
    representation for: ``Decimal`` from a DuckDB numeric column, ``bytes`` from
    a Parquet BLOB, ``NaN``/``Inf`` from a float division, and Arrow scalars
    nested in lists and structs. The two rules that matter:

    - **Never emit a bare ``NaN`` or ``Infinity``.** Those are not JSON, so a
      strict parser rejects the whole document -- one bad cell would cost a whole
      response. They become ``None``.
    - **Never guess at a lossy decode.** A ``Decimal`` becomes its exact decimal
      string, not a float; rounding is the caller's decision, not the
      serializer's.

    Anything unrecognized falls back to ``str()``, so this always terminates and
    always returns something encodable. It is intentionally *not* a validator:
    it will not raise on a type it was never told about.
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
