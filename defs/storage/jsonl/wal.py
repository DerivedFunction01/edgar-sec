"""Append-only write-ahead log (WAL) for JSONL backends."""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Iterable, Iterator

from ..artifacts import atomic_write_text as _atomic_write_text
from ..artifacts import canonical_json
from ..errors import MalformedArtifact
from ..models import BatchReceipt


class JsonlWal:
    """Append-only mutation log with one write/fsync per batch."""

    def __init__(
        self, data_path: str, *, max_entries: int = 1000, max_bytes: int = 1_048_576
    ) -> None:
        self.data_path = data_path
        self.wal_path = re.sub(r"\.jsonl$", "", data_path) + ".wal.jsonl"
        self.max_entries = max(1, int(max_entries))
        self.max_bytes = max(1, int(max_bytes))
        self.entries = 0
        self.bytes = 0
        self._lock = threading.Lock()

    def append_many(self, deltas: Iterable[dict]) -> BatchReceipt:
        items = list(deltas)
        if not items:
            return BatchReceipt(record_count=0, byte_count=0, durable=True)
        text = "".join(canonical_json(delta) + "\n" for delta in items)
        byte_count = len(text.encode("utf-8"))
        with self._lock:
            directory = os.path.dirname(os.path.abspath(self.wal_path))
            os.makedirs(directory, exist_ok=True)
            with open(self.wal_path, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
                fh.flush()
                os.fsync(fh.fileno())
            self.entries += len(items)
            self.bytes += byte_count
        return BatchReceipt(
            record_count=len(items), byte_count=byte_count, durable=True
        )

    def append(self, delta: dict) -> BatchReceipt:
        return self.append_many([delta])

    def flush(self) -> None:
        return None

    def exceeds_thresholds(self) -> bool:
        return self.entries >= self.max_entries or self.bytes >= self.max_bytes

    def replay(self) -> Iterator[dict]:
        """Replay complete lines and ignore only an invalid final partial line."""
        if not os.path.exists(self.wal_path):
            return
        with open(self.wal_path, "rb") as fh:
            raw = fh.read()
        segments = raw.split(b"\n")
        has_terminal_newline = raw.endswith(b"\n")
        complete = segments[:-1]
        trailing = None if has_terminal_newline else segments[-1]
        for index, segment in enumerate(complete, start=1):
            if not segment.strip():
                continue
            try:
                delta = json.loads(segment.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise MalformedArtifact(
                    f"malformed WAL entry at {self.wal_path} line {index}: {exc}"
                ) from exc
            if not isinstance(delta, dict):
                raise MalformedArtifact(f"WAL entry {index} is not an object")
            yield delta
        if trailing and trailing.strip():
            try:
                delta = json.loads(trailing.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                # A process can die after writing only a prefix of its final line.
                return
            if not isinstance(delta, dict):
                raise MalformedArtifact("trailing WAL entry is not an object")
            yield delta

    def reconcile(self, canonical_lines: Iterable[str]) -> BatchReceipt:
        lines = list(canonical_lines)
        byte_count = _atomic_write_text(
            self.data_path, "".join(line + "\n" for line in lines)
        )
        with self._lock:
            _atomic_write_text(self.wal_path, "")
            self.entries = 0
            self.bytes = 0
        return BatchReceipt(
            record_count=len(lines), byte_count=byte_count, durable=True
        )


__all__ = ["JsonlWal"]
