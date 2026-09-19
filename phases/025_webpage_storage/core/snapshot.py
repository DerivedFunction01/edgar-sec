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


def _project_source_row(row: dict) -> ProjectedOccurrence:
    doc_id = str(row["doc_id"])
    compressed = bytes(row["normalized_payload"])
    try:
        clean_bytes = decompress_payload(compressed)
    except zstandard.ZstdError:
        clean_bytes = compressed
    clean_text = clean_bytes.decode("utf-8", errors="replace").replace("\x00", "")
    year, quarter = filing_quarter(row["filing_date"])
    payload = NormalizedPayload(
        doc_id=doc_id,
        clean_text=clean_text,
        payload_sha256=str(row["payload_sha256"]),
    )
    index_row = {
        "occurrence_id": str(row["occurrence_id"]),
        "source_cik": str(row["source_cik"]),
        "accession": str(row["accession"]),
        "form": str(row["form"]),
        "filing_date": str(row["filing_date"])[:10],
        "report_date": None
        if row["report_date"] is None
        else str(row["report_date"])[:10],
        "document_path": str(row["document_path"]),
        "doc_id": doc_id,
        "mime_type": str(row["mime_type"]),
        "byte_size": int(row["byte_size"]),
    }
    return ProjectedOccurrence(index_row, payload, year, quarter)


def iter_project_partition(
    partition_db: str | Path,
    *,
    batch_size: int = 512,
    threads: int | None = None,
    memory_limit: str | None = None,
    temp_directory: str | Path | None = None,
    include_missing: bool = False,
) -> Iterable[list[ProjectedOccurrence]]:
    """Yield projected partition rows in bounded decompressed batches."""
    with PartitionBatchReader(
        partition_db,
        threads=threads,
        memory_limit=memory_limit,
        temp_directory=temp_directory,
    ) as reader:
        for batch in reader.iter_rows(
            batch_size=batch_size, include_missing=include_missing
        ):
            yield [
                _project_source_row(row) for row in batch if "normalized_payload" in row
            ]


def project_partition(partition_db: str | Path) -> list[ProjectedOccurrence]:
    """Project one partition; retained for small offline callers/tests."""
    result: list[ProjectedOccurrence] = []
    for batch in iter_project_partition(partition_db):
        result.extend(batch)
    return result


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


def _payload_batches(
    payloads: list[NormalizedPayload], target_bytes: int
) -> list[list[NormalizedPayload]]:
    batches: list[list[NormalizedPayload]] = []
    current: list[NormalizedPayload] = []
    current_size = 0
    for payload in sorted(payloads, key=lambda item: item.doc_id):
        size = len(payload.clean_text.encode("utf-8"))
        if current and current_size + size > target_bytes:
            batches.append(current)
            current = []
            current_size = 0
        current.append(payload)
        current_size += size
    if current:
        batches.append(current)
    return batches


def _logical_fingerprint(
    index_rows: list[dict], payloads: list[NormalizedPayload]
) -> str:
    payload_hashes = [
        {"doc_id": row.doc_id, "payload_sha256": row.payload_sha256}
        for row in sorted(payloads, key=lambda item: item.doc_id)
    ]
    values = {
        "index": sorted(
            (
                {key: value for key, value in row.items() if key != "payload_file"}
                for row in index_rows
            ),
            key=lambda row: str(row["occurrence_id"]),
        ),
        "payloads": payload_hashes,
    }
    return hashlib.sha256(canonical_json(values).encode("utf-8")).hexdigest()


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


def _write_projected_quarter_batch(
    *,
    root: Path,
    snapshot: str,
    year: int,
    quarter: str,
    occurrences: list[ProjectedOccurrence],
    payload_paths: dict[str, str],
    payload_hashes: dict[str, str],
    payload_sequence: int,
    index_sequence: int,
    target_bytes: int,
) -> tuple[list[dict], int, int]:
    """Write one bounded quarter batch without retaining prior payload text."""
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
    current_payloads: dict[str, NormalizedPayload] = {}
    for occurrence in occurrences:
        doc_id = occurrence.payload.doc_id
        prior_hash = payload_hashes.get(doc_id)
        if prior_hash is not None and prior_hash != occurrence.payload.payload_sha256:
            raise ValueError(f"conflicting payload for doc_id {doc_id}")
        if prior_hash is None:
            payload_hashes[doc_id] = occurrence.payload.payload_sha256
            current_payloads[doc_id] = occurrence.payload
    parts: list[dict] = []
    for payload_batch in _payload_batches(
        list(current_payloads.values()), target_bytes
    ):
        payload_sequence += 1
        path = quarter_dir / f"payload-{payload_sequence:05d}.parquet"
        table = pa.Table.from_pylist(
            [
                {"doc_id": item.doc_id, "clean_text": item.clean_text}
                for item in payload_batch
            ],
            schema=_payload_schema(),
        )
        write_table_atomic(
            table,
            path,
            expected_rows=len(payload_batch),
            expected_schema=_payload_schema(),
            compression="zstd",
            row_group_size=5000,
        )
        relative = _path_for(root, path)
        for item in payload_batch:
            payload_paths[item.doc_id] = relative
        parts.append(
            _part(
                root,
                path,
                kind="payload",
                year=year,
                quarter=quarter,
                row_count=len(payload_batch),
            )
        )
        del table, payload_batch
        force_reclaim_memory()
    index_sequence += 1
    index_path = quarter_dir / f"index-{index_sequence:05d}.parquet"
    index_rows = [
        {
            **occurrence.row,
            "payload_file": payload_paths[occurrence.payload.doc_id],
        }
        for occurrence in sorted(
            occurrences, key=lambda item: str(item.row["occurrence_id"])
        )
    ]
    write_table_atomic(
        pa.Table.from_pylist(index_rows, schema=_index_schema()),
        index_path,
        expected_rows=len(index_rows),
        expected_schema=_index_schema(),
        compression="zstd",
        row_group_size=5000,
    )
    parts.append(
        _part(
            root,
            index_path,
            kind="index",
            year=year,
            quarter=quarter,
            row_count=len(index_rows),
        )
    )
    del index_rows
    force_reclaim_memory()
    return parts, payload_sequence, index_sequence


def publish_projected_snapshot(
    partition_dbs: Iterable[str | Path],
    *,
    artifacts_root: str | Path,
    source_snapshot_ids: Iterable[str] = (),
    operation: str = "merge",
    target_bytes: int = 96 * 1024 * 1024,
    set_current: bool = True,
    batch_size: int = 512,
    threads: int | None = None,
    memory_limit: str | None = None,
    temp_directory: str | Path | None = None,
    progress=None,
) -> dict:
    """Project finalized partition databases and publish a snapshot."""
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
    occurrence_rows: dict[str, tuple] = {}
    doc_quarters: dict[str, tuple[int, str]] = {}
    payload_paths: dict[str, str] = {}
    payload_hashes: dict[str, str] = {}
    logical_hasher = hashlib.sha256()
    parts: list[dict] = []
    payload_sequences: dict[tuple[int, str], int] = defaultdict(int)
    index_sequences: dict[tuple[int, str], int] = defaultdict(int)
    occurrence_count = 0
    payload_count = 0
    for partition_index, path in enumerate(partition_paths, start=1):
        if progress:
            progress({"type": "partition_started", "partition_id": partition_index})
        partition_rows = 0
        for projected_batch in iter_project_partition(
            path,
            batch_size=batch_size,
            threads=threads,
            memory_limit=memory_limit,
            temp_directory=temp_directory,
        ):
            grouped: dict[tuple[int, str], list[ProjectedOccurrence]] = defaultdict(
                list
            )
            for row in projected_batch:
                occurrence_id = str(row.row["occurrence_id"])
                fingerprint = tuple(sorted(row.row.items()))
                prior = occurrence_rows.get(occurrence_id)
                if prior is not None and prior != fingerprint:
                    raise ValueError(f"conflicting occurrence {occurrence_id}")
                if prior is not None:
                    continue
                occurrence_rows[occurrence_id] = fingerprint
                current_quarter = (row.year, row.quarter)
                prior_quarter = doc_quarters.get(row.payload.doc_id)
                if prior_quarter is not None and prior_quarter != current_quarter:
                    raise ValueError(
                        f"doc_id {row.payload.doc_id} occurs in multiple quarters"
                    )
                doc_quarters[row.payload.doc_id] = current_quarter
                logical_hasher.update(
                    canonical_json(
                        {
                            "index": row.row,
                            "payload_sha256": row.payload.payload_sha256,
                        }
                    ).encode("utf-8")
                )
                grouped[current_quarter].append(row)
            for (year, quarter), rows in sorted(grouped.items()):
                before = len(payload_paths)
                (
                    batch_parts,
                    payload_sequences[(year, quarter)],
                    index_sequences[(year, quarter)],
                ) = _write_projected_quarter_batch(
                    root=root,
                    snapshot=physical_id,
                    year=year,
                    quarter=quarter,
                    occurrences=rows,
                    payload_paths=payload_paths,
                    payload_hashes=payload_hashes,
                    payload_sequence=payload_sequences[(year, quarter)],
                    index_sequence=index_sequences[(year, quarter)],
                    target_bytes=target_bytes,
                )
                parts.extend(batch_parts)
                payload_count += len(payload_paths) - before
                if progress:
                    progress(
                        {
                            "type": "quarter_done",
                            "year": year,
                            "quarter": quarter,
                            "rows": len(rows),
                            "payloads": len(payload_paths) - before,
                            "parts": len(batch_parts),
                        }
                    )
            partition_rows += len(projected_batch)
            occurrence_count += len(projected_batch)
            del projected_batch
            force_reclaim_memory()
        if progress:
            progress(
                {
                    "type": "partition_done",
                    "partition_id": partition_index,
                    "rows": partition_rows,
                }
            )
    logical = logical_hasher.hexdigest()
    manifest = make_snapshot_manifest(
        snapshot_id=physical_id,
        schema_version=f"{SNAPSHOT_SCHEMA_VERSION}:{NORMALIZED_SCHEMA_VERSION}",
        resolved_parts=parts,
        added_parts=parts,
        source_snapshot_ids=sorted(set(source_snapshot_ids)),
        dataset=DATASET,
        phase=PHASE,
        effective_cik_count=occurrence_count,
        effective_input_fingerprint=logical,
        provenance={"operation": operation, "logical_fingerprint": logical},
    )
    manifest["logical_fingerprint"] = logical
    manifest["normalized_schema_version"] = NORMALIZED_SCHEMA_VERSION
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
                "rows": occurrence_count,
                "payloads": payload_count,
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
    "ProjectedOccurrence",
    "SnapshotReader",
    "filing_quarter",
    "project_partition",
    "publish_projected_snapshot",
    "snapshot_id",
]
