"""Streaming immutable JSONL checkpoint backend."""

from __future__ import annotations

import os
import re
import threading
from collections.abc import Iterable

from ..artifacts import _fsync_directory
from ..errors import (
    MalformedArtifact,
    SchemaMismatchError,
    StorageError,
    UnsupportedCapability,
)
from ..models import ArtifactRef, BatchReceipt, ChunkRange, DatasetSpec, RunContext
from ..predicates import QueryPlan, evaluate_query
from ..protocols import Record
from .codec import JsonlCodec, write_records_atomic


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


__all__ = ["JsonlChunkBackend"]
