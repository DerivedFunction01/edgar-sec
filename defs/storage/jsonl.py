"""JSONL file backends with append-oriented writes.

``JsonlKeyValueBackend`` is intended for small mutable datasets and previews.
Updates append WAL deltas and do not scan the canonical file. ``load`` builds
the in-memory view once; compaction is deferred until explicitly requested or
the WAL thresholds are reached.

``JsonlChunkBackend`` is intended for production checkpoints. It streams one
record per line into an immutable chunk and publishes it with an atomic rename.
It has no mutable ``set`` path or WAL.
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Iterable, Iterator

from .errors import (
    MalformedArtifact,
    SchemaMismatchError,
    StorageError,
    UnsupportedCapability,
)
from .models import ArtifactRef, BatchReceipt, ChunkRange, DatasetSpec, RunContext
from .predicates import Eq, InSet, QueryPlan, conjunction, evaluate_query
from .protocols import Record


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _fsync_directory(path: str) -> None:
    """Best-effort directory sync after an atomic rename on POSIX."""
    if os.name != "posix":
        return
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        return


def _atomic_write_text(path: str, text: str) -> int:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    tmp_path = path + ".tmp"
    encoded_size = len(text.encode("utf-8"))
    try:
        with open(tmp_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
        _fsync_directory(directory)
        return encoded_size
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


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
        # append_many flushes and fsyncs synchronously; retained for lifecycle parity.
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


class JsonlKeyValueBackend:
    """Mutable keyed JSONL backend with append-only WAL writes."""

    format_name = "jsonl-kv"

    def __init__(
        self,
        data_path: str,
        *,
        max_wal_entries: int = 1000,
        max_wal_bytes: int = 1_048_576,
    ) -> None:
        self.data_path = data_path
        self.wal = JsonlWal(
            data_path, max_entries=max_wal_entries, max_bytes=max_wal_bytes
        )
        self._spec: DatasetSpec | None = None
        self._data: dict[str, Record] | None = None
        self._lock = threading.RLock()

    def init(self, *, spec: DatasetSpec, run: RunContext) -> None:
        self._spec = spec
        os.makedirs(os.path.dirname(os.path.abspath(self.data_path)), exist_ok=True)

    def _require_spec(self) -> DatasetSpec:
        if self._spec is None:
            raise StorageError("backend used before init(spec=..., run=...)")
        return self._spec

    def _load_map(self) -> dict[str, Record]:
        spec = self._require_spec()
        data: dict[str, Record] = {}
        if os.path.exists(self.data_path):
            with open(self.data_path, "r", encoding="utf-8") as fh:
                for number, line in enumerate(fh, start=1):
                    if not line.strip():
                        continue
                    try:
                        record = JsonlCodec.decode(line, key_field=spec.key_field)
                        spec.validate_record(record)
                    except (MalformedArtifact, SchemaMismatchError) as exc:
                        raise MalformedArtifact(
                            f"{self.data_path} line {number}: {exc}"
                        ) from exc
                    data[str(record[spec.key_field])] = record
        for number, delta in enumerate(self.wal.replay(), start=1):
            op = delta.get("op")
            key = delta.get("key")
            if key in (None, ""):
                raise MalformedArtifact(f"WAL entry {number} has no key")
            if op == "set":
                record = dict(delta.get("value") or {})
                record[spec.key_field] = str(key)
                spec.validate_record(record)
                data[str(key)] = record
            elif op == "delete":
                data.pop(str(key), None)
            else:
                raise MalformedArtifact(f"unknown WAL op {op!r} in {self.wal.wal_path}")
        return data

    def _ensure_loaded(self) -> dict[str, Record]:
        if self._data is None:
            self._data = self._load_map()
        return self._data

    def load(self, query: QueryPlan | None = None) -> Iterable[Record]:
        with self._lock:
            records = list(self._ensure_loaded().values())
        return evaluate_query(records, query)

    def set(self, records: Iterable[Record]) -> int:
        spec = self._require_spec()
        items = [dict(record) for record in records]
        if not items:
            return 0
        deltas: list[dict] = []
        for record in items:
            spec.validate_record(record)
            key = str(record[spec.key_field])
            deltas.append({"op": "set", "key": key, "value": record})
        with self._lock:
            # This is the important write optimization: no canonical-file scan
            # occurs when the process has not needed a read-side view yet.
            self.wal.append_many(deltas)
            if self._data is not None:
                for record in items:
                    self._data[str(record[spec.key_field])] = record
        return len(items)

    def write_batch(self, records: Iterable[Record]) -> BatchReceipt:
        spec = self._require_spec()
        items = [dict(record) for record in records]
        if not items:
            return BatchReceipt(record_count=0, byte_count=0, durable=True)
        for record in items:
            spec.validate_record(record)
        deltas = [
            {"op": "set", "key": str(record[spec.key_field]), "value": record}
            for record in items
        ]
        with self._lock:
            receipt = self.wal.append_many(deltas)
            if self._data is not None:
                for record in items:
                    self._data[str(record[spec.key_field])] = record
        return receipt

    def delete(self, query: QueryPlan) -> int:
        spec = self._require_spec()
        predicate = conjunction(query.predicates)
        with self._lock:
            # Unlike set(), delete reports actual removals. Establishing the
            # current view is therefore necessary when this instance has not
            # loaded the file yet.
            data = self._ensure_loaded()
            if predicate is None:
                targets = list(data)
            elif isinstance(predicate, Eq) and predicate.field == spec.key_field:
                targets = [str(predicate.value)]
            elif isinstance(predicate, InSet) and predicate.field == spec.key_field:
                targets = [str(value) for value in predicate.values]
            else:
                targets = [
                    key for key, record in data.items() if predicate.matches(record)
                ]
            targets = [key for key in dict.fromkeys(targets) if key in data]
            if not targets:
                return 0
            receipt = self.wal.append_many(
                {"op": "delete", "key": key} for key in targets
            )
            if self._data is not None:
                for key in targets:
                    self._data.pop(key, None)
            return receipt.record_count

    def commit(self) -> None:
        self._require_spec()
        with self._lock:
            if not self.wal.exceeds_thresholds():
                return
            # Threshold compaction is the deliberate point at which a full
            # canonical scan/rewrite is paid for.
            data = self._ensure_loaded()
            self.wal.reconcile(JsonlCodec.encode(record) for record in data.values())

    def close(self) -> None:
        return None


class JsonlChunkBackend:
    """Streaming immutable JSONL checkpoint backend."""

    format_name = "jsonl-chunk"

    def __init__(
        self, root: str, *, chunk_subdir: str = "chunks", strict_row_count: bool = True
    ) -> None:
        self.root = root
        self.chunk_dir = os.path.join(root, chunk_subdir)
        self.strict_row_count = strict_row_count
        self._spec: DatasetSpec | None = None
        self._lock = threading.RLock()

    def init(self, *, spec: DatasetSpec, run: RunContext) -> None:
        self._spec = spec
        os.makedirs(self.chunk_dir, exist_ok=True)

    def _require_spec(self) -> DatasetSpec:
        if self._spec is None:
            raise StorageError("backend used before init(spec=..., run=...)")
        return self._spec

    def _chunk_filename(self, chunk: ChunkRange) -> str:
        spec = self._require_spec()
        return (
            f"{spec.name}-v{spec.schema_version}-chunk-{chunk.chunk_id:05d}"
            f"-{chunk.start_row:06d}-{chunk.end_row:06d}.jsonl"
        )

    def _parse_chunk_filename(self, name: str) -> dict | None:
        spec = self._require_spec()
        pattern = (
            rf"^{re.escape(spec.name)}-v(?P<version>[A-Za-z0-9.]+)-chunk-"
            r"(?P<chunk_id>\d+)-(?P<start>\d+)-(?P<end>\d+)\.jsonl$"
        )
        match = re.match(pattern, os.path.basename(name))
        if not match:
            return None
        return {
            "version": match.group("version"),
            "chunk_id": int(match.group("chunk_id")),
            "start_row": int(match.group("start")),
            "end_row": int(match.group("end")),
        }

    def load(self, query: QueryPlan | None = None) -> Iterable[Record]:
        records: list[Record] = []
        for ref in sorted(self.list_chunks(), key=lambda item: item.start_row or 0):
            records.extend(self._read_records(ref.path))
        return evaluate_query(records, query)

    def set(self, records: Iterable[Record]) -> int:
        raise UnsupportedCapability("mutable-set", self.format_name)

    def write_batch(self, records: Iterable[Record]) -> BatchReceipt:
        raise UnsupportedCapability("chunk-range-required", self.format_name)

    def delete(self, query: QueryPlan) -> int:
        raise UnsupportedCapability("mutable-delete", self.format_name)

    def commit(self) -> None:
        self._require_spec()

    def close(self) -> None:
        return None

    def _read_records(self, path: str) -> list[Record]:
        spec = self._require_spec()
        records: list[Record] = []
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for number, line in enumerate(fh, start=1):
                    if not line.strip():
                        continue
                    record = JsonlCodec.decode(line)
                    spec.validate_record(record)
                    records.append(record)
        except OSError as exc:
            raise MalformedArtifact(f"cannot read {path}: {exc}") from exc
        return records

    def write_chunk(self, chunk: ChunkRange, records: Iterable[Record]) -> ArtifactRef:
        spec = self._require_spec()
        final_path = os.path.join(self.chunk_dir, self._chunk_filename(chunk))
        tmp_path = final_path + ".tmp"
        count = 0
        byte_count = 0
        keys: set[str] = set()
        try:
            with self._lock:
                with open(tmp_path, "w", encoding="utf-8", newline="\n") as fh:
                    for record in records:
                        spec.validate_record(record)
                        key = str(record[spec.key_field])
                        if key in keys:
                            raise SchemaMismatchError(
                                f"chunk {chunk.chunk_id} contains duplicate key {key}"
                            )
                        keys.add(key)
                        line = JsonlCodec.encode(record) + "\n"
                        fh.write(line)
                        byte_count += len(line.encode("utf-8"))
                        count += 1
                    if self.strict_row_count and count != chunk.row_count:
                        raise SchemaMismatchError(
                            f"chunk {chunk.chunk_id} expects {chunk.row_count} rows, got {count}"
                        )
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp_path, final_path)
                _fsync_directory(self.chunk_dir)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
        return ArtifactRef(
            dataset=spec.name,
            version=spec.schema_version,
            path=final_path,
            format=self.format_name,
            row_count=count,
            bytes=os.path.getsize(final_path),
            chunk_id=chunk.chunk_id,
            start_row=chunk.start_row,
            end_row=chunk.end_row,
        )

    def list_chunks(self) -> list[ArtifactRef]:
        spec = self._require_spec()
        out: list[ArtifactRef] = []
        if not os.path.isdir(self.chunk_dir):
            return out
        for name in sorted(os.listdir(self.chunk_dir)):
            info = self._parse_chunk_filename(name)
            if not info or info["version"] != spec.schema_version:
                continue
            path = os.path.join(self.chunk_dir, name)
            with open(path, "r", encoding="utf-8") as fh:
                row_count = sum(1 for line in fh if line.strip())
            out.append(
                ArtifactRef(
                    dataset=spec.name,
                    version=info["version"],
                    path=path,
                    format=self.format_name,
                    row_count=row_count,
                    bytes=os.path.getsize(path),
                    chunk_id=info["chunk_id"],
                    start_row=info["start_row"],
                    end_row=info["end_row"],
                )
            )
        return out

    def load_chunk_records(self, chunk_id: int) -> list[Record]:
        for ref in self.list_chunks():
            if ref.chunk_id == chunk_id:
                return self._read_records(ref.path)
        raise StorageError(f"no completed checkpoint for chunk {chunk_id}")

    def finalize(self, output_path: str) -> ArtifactRef:
        spec = self._require_spec()
        refs = sorted(self.list_chunks(), key=lambda ref: ref.start_row or 0)
        if not refs:
            raise StorageError("finalize requires at least one completed chunk")
        tmp_path = output_path + ".tmp"
        total = 0
        try:
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8", newline="\n") as out:
                for ref in refs:
                    with open(ref.path, "r", encoding="utf-8") as source:
                        for line in source:
                            if line.strip():
                                out.write(line if line.endswith("\n") else line + "\n")
                                total += 1
                out.flush()
                os.fsync(out.fileno())
            os.replace(tmp_path, output_path)
            _fsync_directory(os.path.dirname(os.path.abspath(output_path)))
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
        return ArtifactRef(
            dataset=spec.name,
            version=spec.schema_version,
            path=output_path,
            format=self.format_name,
            row_count=total,
            bytes=os.path.getsize(output_path),
        )

    def finalize_records(
        self, records: Iterable[Record], output_path: str
    ) -> ArtifactRef:
        spec = self._require_spec()
        count = 0

        def validated():
            nonlocal count
            for record in records:
                value = dict(record)
                spec.validate_record(value)
                count += 1
                yield value

        byte_count = write_records_atomic(validated(), output_path)
        return ArtifactRef(
            dataset=spec.name,
            version=spec.schema_version,
            path=output_path,
            format=self.format_name,
            row_count=count,
            bytes=byte_count,
        )
