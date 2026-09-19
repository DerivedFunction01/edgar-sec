"""Temporal normalized-document snapshots and their read contract."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import zstandard

from defs.runtime.artifacts import (
    make_snapshot_manifest,
    publish_snapshot_manifest,
    resolve_snapshot_manifest,
)
from defs.storage import (
    canonical_json,
    file_sha256,
    force_reclaim_memory,
    pa,
    pq,
    write_table_atomic,
)

from .partition_reader import PartitionBatchReader
from .schemas import NORMALIZED_SCHEMA_VERSION, decompress_payload

PHASE = "webpage_storage"
DATASET = "normalized_documents"
SNAPSHOT_SCHEMA_VERSION = "1"
INDEX_COLUMNS = (
    "occurrence_id",
    "source_cik",
    "accession",
    "form",
    "filing_date",
    "report_date",
    "document_path",
    "doc_id",
    "mime_type",
    "byte_size",
    "payload_file",
)
PAYLOAD_COLUMNS = ("doc_id", "clean_text")


@dataclass(frozen=True, slots=True)
class NormalizedPayload:
    doc_id: str
    clean_text: str
    payload_sha256: str


@dataclass(frozen=True, slots=True)
class ProjectedOccurrence:
    row: dict[str, object]
    payload: NormalizedPayload
    year: int
    quarter: str


def filing_quarter(value: object) -> tuple[int, str]:
    """Return the physical year/quarter for a filing date."""
    text = str(value)[:10]
    try:
        parsed = date.fromisoformat(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"invalid filing date for snapshot partition: {value!r}"
        ) from exc
    return parsed.year, f"QTR{((parsed.month - 1) // 3) + 1}"


def _decompress(compressed: bytes) -> bytes:
    try:
        return decompress_payload(compressed)
    except zstandard.ZstdError:
        return compressed


def _clean_text(clean_bytes: bytes) -> str:
    return clean_bytes.decode("utf-8", errors="replace").replace("\x00", "")


def _project_index_row(raw: dict) -> dict:
    """Build one index row from metadata-only source fields."""
    return {
        "occurrence_id": str(raw["occurrence_id"]),
        "source_cik": str(raw["source_cik"]),
        "accession": str(raw["accession"]),
        "form": str(raw["form"]),
        "filing_date": str(raw["filing_date"])[:10],
        "report_date": None
        if raw["report_date"] is None
        else str(raw["report_date"])[:10],
        "document_path": str(raw["document_path"]),
        "doc_id": str(raw["doc_id"]),
        "mime_type": str(raw["mime_type"]),
        "byte_size": int(raw["byte_size"]),
    }


def _index_schema() -> pa.Schema:
    return pa.schema(
        [
            ("occurrence_id", pa.string()),
            ("source_cik", pa.string()),
            ("accession", pa.string()),
            ("form", pa.string()),
            ("filing_date", pa.string()),
            ("report_date", pa.string()),
            ("document_path", pa.string()),
            ("doc_id", pa.string()),
            ("mime_type", pa.string()),
            ("byte_size", pa.int64()),
            ("payload_file", pa.string()),
        ]
    )


def _payload_schema() -> pa.Schema:
    return pa.schema([("doc_id", pa.string()), ("clean_text", pa.string())])


def _path_for(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _part(
    root: Path,
    path: Path,
    *,
    kind: str,
    year: int,
    quarter: str,
    row_count: int,
    source_snapshot_id: str | None = None,
) -> dict:
    result = {
        "kind": kind,
        "year": year,
        "quarter": quarter,
        "path": _path_for(root, path),
        "artifact_sha256": file_sha256(path),
        "row_count": row_count,
    }
    if source_snapshot_id:
        result["source_snapshot_id"] = source_snapshot_id
    return result


@dataclass(frozen=True, slots=True)
class PlannedPayloadPart:
    """One deterministically planned payload part awaiting materialization."""

    year: int
    quarter: str
    path: Path
    doc_ids: tuple[str, ...]


def plan_payload_parts(
    doc_sizes: dict[tuple[int, str], list[tuple[str, int]]],
    *,
    root: Path,
    snapshot: str,
    target_bytes: int,
) -> list[PlannedPayloadPart]:
    """Pack new documents into payload parts of at most ``target_bytes``.

    Documents are packed in ``doc_id`` order within each quarter. A single
    document larger than ``target_bytes`` becomes its own part. The layout
    depends only on the metadata sizes, never on the source batch size.
    """
    planned: list[PlannedPayloadPart] = []
    for (year, quarter), entries in sorted(doc_sizes.items()):
        quarter_dir = (
            root
            / "manifests"
            / PHASE
            / DATASET
            / "snapshots"
            / snapshot
            / str(year)
            / quarter
        )
        sequence = 0
        current: list[str] = []
        current_bytes = 0
        for doc_id, size in sorted(entries):
            if current and current_bytes + size > target_bytes:
                sequence += 1
                planned.append(
                    PlannedPayloadPart(
                        year,
                        quarter,
                        quarter_dir / f"payload-{sequence:05d}.parquet",
                        tuple(current),
                    )
                )
                current = []
                current_bytes = 0
            current.append(doc_id)
            current_bytes += size
        if current:
            sequence += 1
            planned.append(
                PlannedPayloadPart(
                    year,
                    quarter,
                    quarter_dir / f"payload-{sequence:05d}.parquet",
                    tuple(current),
                )
            )
    return planned


def _write_payload_part(
    root: Path,
    part: PlannedPayloadPart,
    payload_rows: list[tuple[str, str]],
) -> dict:
    """Write one planned payload part and return its manifest entry."""
    part.path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(
        [{"doc_id": doc_id, "clean_text": text} for doc_id, text in payload_rows],
        schema=_payload_schema(),
    )
    write_table_atomic(
        table,
        part.path,
        expected_rows=len(payload_rows),
        expected_schema=_payload_schema(),
        compression="zstd",
        row_group_size=5000,
    )
    entry = _part(
        root,
        part.path,
        kind="payload",
        year=part.year,
        quarter=part.quarter,
        row_count=len(payload_rows),
    )
    del table
    force_reclaim_memory()
    return entry


def _write_quarter_index_part(
    root: Path,
    snapshot: str,
    year: int,
    quarter: str,
    index_rows: list[dict],
) -> dict:
    """Write the single index part for one quarter of a publication."""
    quarter_dir = (
        root
        / "manifests"
        / PHASE
        / DATASET
        / "snapshots"
        / snapshot
        / str(year)
        / quarter
    )
    quarter_dir.mkdir(parents=True, exist_ok=True)
    index_path = quarter_dir / "index-00001.parquet"
    ordered = sorted(index_rows, key=lambda row: str(row["occurrence_id"]))
    write_table_atomic(
        pa.Table.from_pylist(ordered, schema=_index_schema()),
        index_path,
        expected_rows=len(ordered),
        expected_schema=_index_schema(),
        compression="zstd",
        row_group_size=5000,
    )
    entry = _part(
        root,
        index_path,
        kind="index",
        year=year,
        quarter=quarter,
        row_count=len(ordered),
    )
    del ordered
    force_reclaim_memory()
    return entry


def snapshot_id(
    *,
    operation: str,
    source_snapshot_ids: Iterable[str],
    artifact_hashes: Iterable[str],
    schema_version: str = SNAPSHOT_SCHEMA_VERSION,
) -> str:
    value = {
        "operation": operation,
        "source_snapshot_ids": sorted(set(source_snapshot_ids)),
        "artifact_hashes": sorted(artifact_hashes),
        "schema_version": schema_version,
    }
    return (
        "snap_" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()[:12]
    )


def _materialize_planned_parts(
    planned_parts: list[PlannedPayloadPart],
    *,
    root: Path,
    partition_paths: list[Path],
    doc_meta: dict[str, dict],
    target_bytes: int,
    batch_size: int,
    threads: int | None,
    memory_limit: str | None,
    temp_directory: str | Path | None,
    progress=None,
) -> list[dict]:
    """Fetch blobs per planned part, verify hashes, and write payload parts."""
    parts: list[dict] = []
    if not planned_parts:
        return parts
    readers = [
        PartitionBatchReader(
            path,
            threads=threads,
            memory_limit=memory_limit,
            temp_directory=temp_directory,
        )
        for path in partition_paths
    ]
    try:
        for part in planned_parts:
            by_partition: dict[int, list[str]] = defaultdict(list)
            for doc_id in part.doc_ids:
                by_partition[int(doc_meta[doc_id]["partition_index"])].append(doc_id)
            texts: dict[str, str] = {}
            for partition_index, doc_ids in by_partition.items():
                for chunk in readers[partition_index - 1].fetch_payloads(
                    doc_ids, chunk_size=max(1, batch_size)
                ):
                    for row in chunk:
                        doc_id = str(row["source_doc_id"])
                        clean_bytes = _decompress(bytes(row["normalized_payload"]))
                        if hashlib.sha256(clean_bytes).hexdigest() != str(
                            row["payload_sha256"]
                        ):
                            raise ValueError(
                                f"payload hash mismatch for doc_id {doc_id}"
                            )
                        texts[doc_id] = _clean_text(clean_bytes)
                        del clean_bytes
            missing = [doc_id for doc_id in part.doc_ids if doc_id not in texts]
            if missing:
                raise ValueError(
                    f"missing payload for doc_id(s): {', '.join(missing[:5])}"
                )
            parts.append(
                _write_payload_part(
                    root,
                    part,
                    [(doc_id, texts[doc_id]) for doc_id in part.doc_ids],
                )
            )
            if progress:
                progress(
                    {
                        "type": "part_written",
                        "year": part.year,
                        "quarter": part.quarter,
                        "payloads": len(part.doc_ids),
                        "path": str(part.path),
                    }
                )
            del texts
            force_reclaim_memory()
    finally:
        for reader in readers:
            reader.close()
    return parts


def publish_projected_snapshot(
    partition_dbs: Iterable[str | Path],
    *,
    artifacts_root: str | Path,
    source_snapshot_ids: Iterable[str] = (),
    operation: str = "merge",
    target_bytes: int = 96 * 1024 * 1024,
    set_current: bool = True,
    batch_size: int = 4096,
    threads: int | None = None,
    memory_limit: str | None = None,
    temp_directory: str | Path | None = None,
    progress=None,
) -> dict:
    """Publish a snapshot via a two-pass metadata plan and blob materialization."""
    root = Path(artifacts_root).resolve()
    partition_paths = [Path(path) for path in partition_dbs]
    if not partition_paths:
        raise ValueError("at least one partition database is required")
    artifact_hashes = [file_sha256(path) for path in partition_paths]
    physical_id = snapshot_id(
        operation=operation,
        source_snapshot_ids=source_snapshot_ids,
        artifact_hashes=artifact_hashes,
        schema_version=f"{SNAPSHOT_SCHEMA_VERSION}:{NORMALIZED_SCHEMA_VERSION}",
    )

    # Pass 1: metadata-only scan; conflict checks and part planning need no blobs.
    index_rows: dict[str, dict] = {}
    doc_quarters: dict[str, tuple[int, str]] = {}
    doc_meta: dict[str, dict] = {}
    doc_sizes: dict[tuple[int, str], list[tuple[str, int]]] = defaultdict(list)
    logical_hasher = hashlib.sha256()
    for partition_index, path in enumerate(partition_paths, start=1):
        if progress:
            progress({"type": "partition_started", "partition_id": partition_index})
        partition_rows = 0
        with PartitionBatchReader(
            path,
            threads=threads,
            memory_limit=memory_limit,
            temp_directory=temp_directory,
        ) as reader:
            for batch in reader.iter_rows(
                batch_size=max(1, batch_size),
                include_missing=True,
                with_payload=False,
            ):
                for raw in batch:
                    if "payload_sha256" not in raw:
                        continue
                    row = _project_index_row(raw)
                    occurrence_id = row["occurrence_id"]
                    doc_id = row["doc_id"]
                    year, quarter = filing_quarter(raw["filing_date"])
                    prior = index_rows.get(occurrence_id)
                    if prior is not None:
                        if prior != row:
                            raise ValueError(f"conflicting occurrence {occurrence_id}")
                        continue
                    prior_quarter = doc_quarters.get(doc_id)
                    if prior_quarter is not None and prior_quarter != (year, quarter):
                        raise ValueError(f"doc_id {doc_id} occurs in multiple quarters")
                    doc_quarters[doc_id] = (year, quarter)
                    payload_sha = str(raw["payload_sha256"])
                    meta = doc_meta.get(doc_id)
                    if meta is None:
                        doc_meta[doc_id] = {
                            "payload_sha256": payload_sha,
                            "byte_size": int(raw["byte_size"]),
                            "partition_index": partition_index,
                        }
                        doc_sizes[(year, quarter)].append(
                            (doc_id, int(raw["byte_size"]))
                        )
                    elif meta["payload_sha256"] != payload_sha:
                        raise ValueError(f"conflicting payload for doc_id {doc_id}")
                    index_rows[occurrence_id] = row
                    logical_hasher.update(
                        canonical_json(
                            {"index": row, "payload_sha256": payload_sha}
                        ).encode("utf-8")
                    )
                partition_rows += len(batch)
                del batch
                force_reclaim_memory()
        if progress:
            progress(
                {
                    "type": "partition_done",
                    "partition_id": partition_index,
                    "rows": partition_rows,
                }
            )

    planned_parts = plan_payload_parts(
        doc_sizes,
        root=root,
        snapshot=physical_id,
        target_bytes=target_bytes,
    )
    doc_payload_file = {
        doc_id: _path_for(root, part.path)
        for part in planned_parts
        for doc_id in part.doc_ids
    }
    for row in index_rows.values():
        row["payload_file"] = doc_payload_file[row["doc_id"]]

    # Pass 2: materialize one planned part at a time.
    parts = _materialize_planned_parts(
        planned_parts,
        root=root,
        partition_paths=partition_paths,
        doc_meta=doc_meta,
        target_bytes=target_bytes,
        batch_size=batch_size,
        threads=threads,
        memory_limit=memory_limit,
        temp_directory=temp_directory,
        progress=progress,
    )
    quarter_groups: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for row in index_rows.values():
        quarter_groups[doc_quarters[row["doc_id"]]].append(row)
    for (year, quarter), rows in sorted(quarter_groups.items()):
        parts.append(_write_quarter_index_part(root, physical_id, year, quarter, rows))
        if progress:
            progress(
                {
                    "type": "quarter_done",
                    "year": year,
                    "quarter": quarter,
                    "rows": len(rows),
                    "payloads": sum(
                        1 for part in planned_parts if part.quarter == quarter
                    ),
                    "parts": 1,
                }
            )
    parts.sort(key=lambda part: str(part["path"]))
    logical = logical_hasher.hexdigest()
    manifest = make_snapshot_manifest(
        snapshot_id=physical_id,
        schema_version=f"{SNAPSHOT_SCHEMA_VERSION}:{NORMALIZED_SCHEMA_VERSION}",
        resolved_parts=parts,
        added_parts=parts,
        source_snapshot_ids=sorted(set(source_snapshot_ids)),
        dataset=DATASET,
        phase=PHASE,
        effective_cik_count=len(index_rows),
        effective_input_fingerprint=logical,
        provenance={"operation": operation, "logical_fingerprint": logical},
    )
    manifest["logical_fingerprint"] = logical
    manifest["normalized_schema_version"] = NORMALIZED_SCHEMA_VERSION
    manifest["effective_payload_count"] = len(doc_meta)
    publish_snapshot_manifest(
        manifest,
        artifacts_root=root,
        phase=PHASE,
        dataset=DATASET,
        set_current=set_current,
    )
    if progress:
        progress(
            {
                "type": "publish_manifest",
                "snapshot_id": physical_id,
                "rows": len(index_rows),
                "payloads": len(doc_meta),
            }
        )
    return manifest


class SnapshotReader:
    """Read effective normalized metadata and payloads without path knowledge."""

    def __init__(self, artifacts_root: str | Path, snapshot_id: str | None = None):
        self.artifacts_root = Path(artifacts_root).resolve()
        self.manifest, self.manifest_path = resolve_snapshot_manifest(
            snapshot_id,
            artifacts_root=self.artifacts_root,
            phase=PHASE,
            dataset=DATASET,
        )
        self._part_hashes = {
            str(part["path"]): str(part["artifact_sha256"])
            for part in self.manifest.get("resolved_parts", [])
        }

    @property
    def snapshot_id(self) -> str:
        return str(self.manifest["snapshot_id"])

    def _parts(self, kind: str, year: int | None = None, quarter: str | None = None):
        for part in self.manifest.get("resolved_parts", []):
            if part.get("kind", "") != kind:
                continue
            if year is not None and int(part.get("year")) != year:
                continue
            if quarter is not None and part.get("quarter") != quarter:
                continue
            yield part

    def _safe_path(self, relative: str) -> Path:
        expected = self._part_hashes.get(relative)
        if expected is None:
            raise ValueError(f"unlisted snapshot part: {relative}")
        path = (self.artifacts_root / relative).resolve()
        try:
            path.relative_to(self.artifacts_root)
        except ValueError as exc:
            raise ValueError(
                f"snapshot part escapes artifact root: {relative}"
            ) from exc
        if not path.is_file():
            raise FileNotFoundError(f"snapshot part not found: {relative}")
        if file_sha256(path) != expected:
            raise ValueError(f"snapshot part hash mismatch: {relative}")
        return path

    def index_rows(
        self, *, year: int | None = None, quarter: str | None = None, **filters
    ) -> list[dict]:
        rows: dict[str, dict] = {}
        for part in self._parts("index", year, quarter):
            path = self._safe_path(str(part["path"]))
            table = pq.read_table(path, columns=list(INDEX_COLUMNS))
            for row in table.to_pylist():
                key = str(row["occurrence_id"])
                existing = rows.get(key)
                if existing is not None and existing != row:
                    raise ValueError(f"conflicting layered occurrence {key}")
                rows[key] = row
        return [
            row
            for row in rows.values()
            if all(
                value is None or row.get(key) == value for key, value in filters.items()
            )
        ]

    def payload_rows(self, index_rows: Iterable[dict]) -> list[dict]:
        wanted: dict[str, set[str]] = defaultdict(set)
        for row in index_rows:
            wanted[str(row["payload_file"])].add(str(row["doc_id"]))
        result: dict[str, dict] = {}
        for relative, doc_ids in wanted.items():
            path = self._safe_path(relative)
            table = pq.read_table(path, columns=list(PAYLOAD_COLUMNS))
            for row in table.to_pylist():
                if str(row["doc_id"]) in doc_ids:
                    result[str(row["doc_id"])] = row
        return [result[key] for key in sorted(result)]

    def find(self, **filters) -> list[dict]:
        return self.index_rows(**filters)


__all__ = [
    "DATASET",
    "INDEX_COLUMNS",
    "PAYLOAD_COLUMNS",
    "PHASE",
    "NormalizedPayload",
    "PlannedPayloadPart",
    "ProjectedOccurrence",
    "SnapshotReader",
    "filing_quarter",
    "plan_payload_parts",
    "publish_projected_snapshot",
    "snapshot_id",
]
