"""JSON-safe serialization of query results (no pandas)."""

from __future__ import annotations

import base64
import datetime
import decimal
import math
from collections.abc import Mapping, Sequence
from typing import Any


def json_safe(value: Any) -> Any:
    """Convert a value into something json.dumps can serialize.

    Timestamps/datetimes become ISO strings, decimals become strings, bytes
    become base64, and NaN/Inf become None. Nested mappings and sequences are
    converted recursively; anything unknown falls back to ``str()``.
    """
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
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
    """``json.dumps`` with viewer normalization applied."""
    import json

    return json.dumps(json_safe(value), default=str)
