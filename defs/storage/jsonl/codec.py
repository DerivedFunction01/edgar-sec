"""JSONL record codec and atomic file writing primitives."""

from __future__ import annotations

import json
from collections.abc import Iterable

from ..artifacts import atomic_write_text as _atomic_write_text
from ..artifacts import canonical_json
from ..errors import MalformedArtifact
from ..protocols import Record


def write_records_atomic(records: Iterable[Record], path: str) -> int:
    """Write an iterable of records as an atomic JSONL artifact."""
    text = "".join(canonical_json(record) + "\n" for record in records)
    return _atomic_write_text(path, text)


class JsonlCodec:
    """Deterministic JSON object line codec."""

    @staticmethod
    def encode(record: Record) -> str:
        return canonical_json(record)

    @staticmethod
    def decode(line: str, key_field: str | None = None) -> Record:
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise MalformedArtifact(f"invalid JSONL line: {exc}") from exc
        if not isinstance(value, dict):
            raise MalformedArtifact("JSONL line must decode to an object")
        # Read old generic key/value lines, but always expose a normal record.
        if key_field and key_field not in value and {"key", "value"} <= set(value):
            payload = value["value"]
            if not isinstance(payload, dict):
                raise MalformedArtifact("wrapped JSONL value must be an object")
            payload = dict(payload)
            payload[key_field] = value["key"]
            return payload
        return value


__all__ = ["JsonlCodec", "write_records_atomic"]
