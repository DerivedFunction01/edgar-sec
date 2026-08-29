"""Parquet file backend with immutable writes and chunk checkpoints."""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Iterable

import pyarrow as pa
import pyarrow.parquet as pq

from .artifacts import atomic_write_text as _atomic_write_text
from .artifacts import canonical_json
from .errors import MalformedArtifact, SchemaMismatchError, StorageError
from .models import ArtifactRef, BatchReceipt, ChunkRange, DatasetSpec, RunContext
from .predicates import QueryPlan, conjunction, evaluate_query
from .protocols import Record


def _atomic_write_table(
    table: pa.Table,
    final_path: str | os.PathLike[str],
    expected_rows: int | None = None,
    expected_schema: pa.Schema | None = None,
) -> int:
    final_path_str = os.fspath(final_path)
    directory = os.path.dirname(os.path.abspath(final_path_str))
    os.makedirs(directory, exist_ok=True)
    tmp_path = final_path_str + ".tmp"
    try:
        pq.write_table(table, tmp_path)
        written = pq.read_table(tmp_path)
        if expected_rows is not None and written.num_rows != expected_rows:
            raise SchemaMismatchError(
                f"artifact validation failed: wrote {expected_rows} rows, read {written.num_rows}"
            )
        if expected_schema is not None and written.schema != expected_schema:
            raise SchemaMismatchError(
                "artifact validation failed: schema drift detected"
            )
        os.replace(tmp_path, final_path_str)
        if os.name == "posix":
            try:
                directory_fd = os.open(directory, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError:
                pass
        return os.path.getsize(final_path_str)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def write_table_atomic(
    table: pa.Table,
    final_path: str | os.PathLike[str],
    *,
    expected_rows: int | None = None,
    expected_schema: pa.Schema | None = None,
) -> int:
    return _atomic_write_table(
        table, final_path, expected_rows=expected_rows, expected_schema=expected_schema
    )


def chunk_filename(spec: DatasetSpec, chunk: ChunkRange) -> str:
    return f"{spec.name}-v{spec.schema_version}-chunk-{chunk.chunk_id:05d}-{chunk.start_row:06d}-{chunk.end_row:06d}.parquet"


def parse_chunk_filename(spec: DatasetSpec, name: str) -> dict | None:
    pattern = rf"^{re.escape(spec.name)}-v(?P<version>[A-Za-z0-9.]+)-chunk-(?P<chunk_id>\d+)-(?P<start>\d+)-(?P<end>\d+)\.parquet$"
    match = re.match(pattern, os.path.basename(name))
    if not match:
        return None
    return {
        "version": match.group("version"),
        "chunk_id": int(match.group("chunk_id")),
        "start_row": int(match.group("start")),
        "end_row": int(match.group("end")),
    }


class ParquetBackend:
    """Immutable-fragment Parquet backend and checkpoint store."""

    format_name = "parquet"

    def __init__(
        self,
        root: str,
        *,
        chunk_subdir: str = "chunks",
        fragment_subdir: str = "fragments",
    ) -> None:
        self.root = root
        self.chunk_dir = os.path.join(root, chunk_subdir)
        self.fragment_dir = os.path.join(root, fragment_subdir)
        self._spec: DatasetSpec | None = None
        self._run: RunContext | None = None
        self._manifest: dict | None = None
        self._lock = threading.RLock()

    # lifecycle --------------------------------------------------------------

    def init(self, *, spec: DatasetSpec, run: RunContext) -> None:
        if spec.arrow_schema is None:
            raise StorageError("ParquetBackend requires DatasetSpec.arrow_schema")
        self._spec = spec
        self._run = run
        os.makedirs(self.root, exist_ok=True)
        os.makedirs(self.chunk_dir, exist_ok=True)
        os.makedirs(self.fragment_dir, exist_ok=True)
        self._manifest = self._read_manifest()

    def _require_spec(self) -> DatasetSpec:
        if self._spec is None:
            raise StorageError("backend used before init(spec=..., run=...)")
        return self._spec

    def _manifest_path(self) -> str:
        spec = self._require_spec()
        return os.path.join(
            self.root, f"{spec.name}-v{spec.schema_version}.manifest.json"
        )

    def _logical_path(self) -> str:
        spec = self._require_spec()
        return os.path.join(self.root, f"{spec.name}-v{spec.schema_version}.parquet")

    def _read_manifest(self) -> dict:
        spec = self._require_spec()
        path = self._manifest_path()
        if not os.path.exists(path):
            entries = []
            if os.path.exists(self._logical_path()):
                entries.append(
                    {
                        "generation": 0,
                        "kind": "upsert",
                        "path": os.path.basename(self._logical_path()),
                    }
                )
            return {
                "dataset": spec.name,
                "schema_version": spec.schema_version,
                "next_generation": 1,
                "entries": entries,
            }
        try:
            with open(path, "r", encoding="utf-8") as fh:
                value = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            raise MalformedArtifact(
                f"cannot read Parquet manifest {path}: {exc}"
            ) from exc
        if (
            value.get("dataset") != spec.name
            or value.get("schema_version") != spec.schema_version
        ):
            raise SchemaMismatchError(f"manifest {path} does not match dataset spec")
        if not isinstance(value.get("entries"), list):
            raise MalformedArtifact(f"manifest {path} has no entries list")
        return value

    def _publish_manifest(self) -> None:
        assert self._manifest is not None
        _atomic_write_text(self._manifest_path(), canonical_json(self._manifest) + "\n")

    def _entry_path(self, entry: dict) -> str:
        path = entry["path"]
        if os.path.isabs(path):
            return path
        if entry.get("kind") == "upsert" and path == os.path.basename(
            self._logical_path()
        ):
            return self._logical_path()
        return os.path.join(self.fragment_dir, path)

    def _next_generation(self) -> int:
        assert self._manifest is not None
        value = int(self._manifest.get("next_generation", 1))
        self._manifest["next_generation"] = value + 1
        return value

    def commit(self) -> None:
        self._require_spec()

    def close(self) -> None:
        return None

    # logical store -----------------------------------------------------------

    def _records_from_entries(self) -> dict[str, Record]:
        spec = self._require_spec()
        assert self._manifest is not None
        records: dict[str, Record] = {}
        for entry in sorted(
            self._manifest["entries"], key=lambda item: int(item["generation"])
        ):
            kind = entry.get("kind")
            if kind == "upsert":
                path = self._entry_path(entry)
                try:
                    table = pq.read_table(path, schema=spec.arrow_schema)
                except (OSError, pa.ArrowException) as exc:
                    raise MalformedArtifact(
                        f"cannot read Parquet fragment {path}: {exc}"
                    ) from exc
                for record in table.to_pylist():
                    spec.validate_record(record)
                    records[str(record[spec.key_field])] = record
            elif kind == "delete":
                for key in entry.get("keys", []):
                    records.pop(str(key), None)
            else:
                raise MalformedArtifact(f"unknown Parquet manifest entry kind {kind!r}")
        return records

    def load(self, query: QueryPlan | None = None) -> Iterable[Record]:
        with self._lock:
            records = list(self._records_from_entries().values())
        return evaluate_query(records, query)

    def set(self, records: Iterable[Record]) -> int:
        receipt = self.write_batch(records)
        return receipt.record_count

    def write_batch(self, records: Iterable[Record]) -> BatchReceipt:
        spec = self._require_spec()
        items = [dict(record) for record in records]
        if not items:
            return BatchReceipt(record_count=0, byte_count=0, durable=True)
        for record in items:
            spec.validate_record(record)
        keys = [str(record[spec.key_field]) for record in items]
        if len(set(keys)) != len(keys):
            raise SchemaMismatchError("Parquet batch contains duplicate logical keys")
        assert spec.arrow_schema is not None
        with self._lock:
            generation = self._next_generation()
            filename = (
                f"{spec.name}-v{spec.schema_version}-fragment-{generation:012d}.parquet"
            )
            path = os.path.join(self.fragment_dir, filename)
            byte_count = _atomic_write_table(
                pa.Table.from_pylist(items, schema=spec.arrow_schema),
                path,
                expected_rows=len(items),
                expected_schema=spec.arrow_schema,
            )
            assert self._manifest is not None
            self._manifest["entries"].append(
                {
                    "generation": generation,
                    "kind": "upsert",
                    "path": filename,
                    "row_count": len(items),
                }
            )
            self._publish_manifest()
        return BatchReceipt(
            record_count=len(items),
            byte_count=byte_count,
            durable=True,
            generation=generation,
        )

    def delete(self, query: QueryPlan) -> int:
        self._require_spec()
        with self._lock:
            # Deletion reports actual rows removed. Without a separate key
            # index, establish the current view once to distinguish an absent
            # key from a real tombstone target. The write itself remains an
            # append-only manifest mutation rather than a dataset rewrite.
            predicate = conjunction(query.predicates)
            records = self._records_from_entries()
            targets = [
                key
                for key, record in records.items()
                if predicate is None or predicate.matches(record)
            ]
            targets = list(dict.fromkeys(targets))
            if not targets:
                return 0
            generation = self._next_generation()
            assert self._manifest is not None
            self._manifest["entries"].append(
                {
                    "generation": generation,
                    "kind": "delete",
                    "keys": targets,
                }
            )
            self._publish_manifest()
            return len(targets)

    def compact(self) -> ArtifactRef:
        """Materialize the current fragment view into the logical Parquet file."""
        spec = self._require_spec()
        records = list(self._records_from_entries().values())
        assert spec.arrow_schema is not None
        byte_count = _atomic_write_table(
            pa.Table.from_pylist(records, schema=spec.arrow_schema),
            self._logical_path(),
            expected_rows=len(records),
            expected_schema=spec.arrow_schema,
        )
        with self._lock:
            self._manifest = {
                "dataset": spec.name,
                "schema_version": spec.schema_version,
                "next_generation": 1,
                "entries": [
                    {
                        "generation": 0,
                        "kind": "upsert",
                        "path": os.path.basename(self._logical_path()),
                        "row_count": len(records),
                    }
                ],
            }
            self._publish_manifest()
        return ArtifactRef(
            dataset=spec.name,
            version=spec.schema_version,
            path=self._logical_path(),
            format=self.format_name,
            row_count=len(records),
            bytes=byte_count,
        )

    # immutable chunks --------------------------------------------------------

    def write_chunk(self, chunk: ChunkRange, records: Iterable[Record]) -> ArtifactRef:
        spec = self._require_spec()
        items = [dict(record) for record in records]
        if len(items) != chunk.row_count:
            raise SchemaMismatchError(
                f"chunk {chunk.chunk_id} expects {chunk.row_count} rows, got {len(items)}"
            )
        for record in items:
            spec.validate_record(record)
        keys = [str(record[spec.key_field]) for record in items]
        if len(set(keys)) != len(keys):
            raise SchemaMismatchError(f"chunk {chunk.chunk_id} contains duplicate keys")
        assert spec.arrow_schema is not None
        table = pa.Table.from_pylist(items, schema=spec.arrow_schema)
        path = os.path.join(self.chunk_dir, chunk_filename(spec, chunk))
        with self._lock:
            byte_count = _atomic_write_table(
                table,
                path,
                expected_rows=chunk.row_count,
                expected_schema=spec.arrow_schema,
            )
        return ArtifactRef(
            dataset=spec.name,
            version=spec.schema_version,
            path=path,
            format=self.format_name,
            row_count=len(items),
            bytes=byte_count,
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
            info = parse_chunk_filename(spec, name)
            if not info or info["version"] != spec.schema_version:
                continue
            path = os.path.join(self.chunk_dir, name)
            try:
                row_count = pq.ParquetFile(path).metadata.num_rows
            except (OSError, pa.ArrowException) as exc:
                raise MalformedArtifact(f"cannot inspect chunk {path}: {exc}") from exc
            out.append(
                ArtifactRef(
                    dataset=spec.name,
                    version=spec.schema_version,
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
        spec = self._require_spec()
        assert spec.arrow_schema is not None
        for ref in self.list_chunks():
            if ref.chunk_id == chunk_id:
                try:
                    table = pq.read_table(ref.path, schema=spec.arrow_schema)
                except (OSError, pa.ArrowException) as exc:
                    raise MalformedArtifact(
                        f"cannot read chunk {ref.path}: {exc}"
                    ) from exc
                return table.to_pylist()
        raise StorageError(f"no completed checkpoint for chunk {chunk_id}")

    def finalize(self, output_path: str) -> ArtifactRef:
        spec = self._require_spec()
        refs = sorted(self.list_chunks(), key=lambda ref: ref.start_row or 0)
        if refs:
            assert spec.arrow_schema is not None
            tables = []
            total = 0
            for ref in refs:
                table = pq.read_table(ref.path, schema=spec.arrow_schema)
                tables.append(table)
                total += table.num_rows
            table = pa.concat_tables(tables) if len(tables) > 1 else tables[0]
        else:
            rows = list(self._records_from_entries().values())
            assert spec.arrow_schema is not None
            table = pa.Table.from_pylist(rows, schema=spec.arrow_schema)
            total = len(rows)
        byte_count = _atomic_write_table(
            table, output_path, expected_rows=total, expected_schema=spec.arrow_schema
        )
        return ArtifactRef(
            dataset=spec.name,
            version=spec.schema_version,
            path=output_path,
            format=self.format_name,
            row_count=total,
            bytes=byte_count,
        )

    def finalize_records(
        self, records: Iterable[Record], output_path: str
    ) -> ArtifactRef:
        spec = self._require_spec()
        items = [dict(record) for record in records]
        for record in items:
            spec.validate_record(record)
        assert spec.arrow_schema is not None
        byte_count = _atomic_write_table(
            pa.Table.from_pylist(items, schema=spec.arrow_schema),
            output_path,
            expected_rows=len(items),
            expected_schema=spec.arrow_schema,
        )
        return ArtifactRef(
            dataset=spec.name,
            version=spec.schema_version,
            path=output_path,
            format=self.format_name,
            row_count=len(items),
            bytes=byte_count,
        )
