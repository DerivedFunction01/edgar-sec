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
from defs.sql import Select, Table, col, make_sql_executor
from defs.storage import (
    canonical_json,
    file_sha256,
    pa,
    pq,
    write_table_atomic,
)

from .schemas import (
    FILING_OCCURRENCES_TABLE,
    NORMALIZED_DOCUMENTS_TABLE,
    NORMALIZED_SCHEMA_VERSION,
    decompress_payload,
)

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


def _select_rows(path: Path, table: str, columns: tuple[str, ...]) -> list[dict]:
    executor = make_sql_executor(path, dialect="sqlite")
    try:
        query = Select(
            source=Table(table),
            projection=tuple(col(column) for column in columns),
        )
        return executor.query(executor.compiler.compile(query))
    finally:
        executor.close()


def _choose_normalized(rows: Iterable[dict]) -> dict[str, dict]:
    chosen: dict[str, dict] = {}
    payloads: dict[str, set[str]] = defaultdict(set)
    fingerprints: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        source_doc_id = str(row["source_doc_id"])
        payloads[source_doc_id].add(str(row["payload_sha256"]))
        fingerprints[source_doc_id].add(str(row.get("processor_fingerprint", "")))
        current = chosen.get(source_doc_id)
        key = (
            int(row.get("schema_version", 0)),
            str(row.get("processor_fingerprint", "")),
            str(row.get("normalized_artifact_id", "")),
        )
        if current is None or key > current["_selection_key"]:
            chosen[source_doc_id] = {**row, "_selection_key": key}
    conflicts = [
        doc_id
        for doc_id, hashes in payloads.items()
        if len(hashes) > 1 and len(fingerprints[doc_id]) == 1
    ]
    if conflicts:
        raise ValueError(
            "conflicting normalized payloads for doc_id(s): "
            + ", ".join(sorted(conflicts))
        )
    for row in chosen.values():
        row.pop("_selection_key", None)
    return chosen


def project_partition(partition_db: str | Path) -> list[ProjectedOccurrence]:
    """Project normalized occurrence/payload rows from one partition database."""
    path = Path(partition_db)
    occurrences = _select_rows(
        path,
        FILING_OCCURRENCES_TABLE,
        (
            "occurrence_id",
            "source_cik",
            "accession",
            "document_path",
            "form",
            "filing_date",
            "report_date",
            "doc_id",
        ),
    )
    normalized = _choose_normalized(
        _select_rows(
            path,
            NORMALIZED_DOCUMENTS_TABLE,
            (
                "normalized_artifact_id",
                "source_doc_id",
                "byte_size",
                "normalized_payload",
                "payload_sha256",
                "mime_type",
                "processor_fingerprint",
                "schema_version",
            ),
        )
    )
    result: list[ProjectedOccurrence] = []
    for occurrence in occurrences:
        doc_id = str(occurrence["doc_id"])
        normalized_row = normalized.get(doc_id)
        if normalized_row is None:
            continue
        compressed = bytes(normalized_row["normalized_payload"])
        try:
            clean_bytes = decompress_payload(compressed)
        except zstandard.ZstdError:
            clean_bytes = compressed
        clean_text = clean_bytes.decode("utf-8", errors="replace").replace("\x00", "")
        year, quarter = filing_quarter(occurrence["filing_date"])
        payload = NormalizedPayload(
            doc_id=doc_id,
            clean_text=clean_text,
            payload_sha256=str(normalized_row["payload_sha256"]),
        )
        index_row = {
            "occurrence_id": str(occurrence["occurrence_id"]),
            "source_cik": str(occurrence["source_cik"]),
            "accession": str(occurrence["accession"]),
            "form": str(occurrence["form"]),
            "filing_date": str(occurrence["filing_date"])[:10],
            "report_date": (
                None
                if occurrence["report_date"] is None
                else str(occurrence["report_date"])[:10]
            ),
            "document_path": str(occurrence["document_path"]),
            "doc_id": doc_id,
            "mime_type": str(normalized_row["mime_type"]),
            "byte_size": int(normalized_row["byte_size"]),
        }
        result.append(ProjectedOccurrence(index_row, payload, year, quarter))
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


def write_quarter_parts(
    *,
    root: str | Path,
    snapshot: str,
    year: int,
    quarter: str,
    occurrences: list[ProjectedOccurrence],
    target_bytes: int = 96 * 1024 * 1024,
) -> list[dict]:
    """Write one self-contained quarter and return manifest part entries."""
    artifact_root = Path(root).resolve()
    quarter_dir = (
        artifact_root
        / "manifests"
        / PHASE
        / DATASET
        / "snapshots"
        / snapshot
        / str(year)
        / quarter
    )
    quarter_dir.mkdir(parents=True, exist_ok=True)
    by_doc: dict[str, NormalizedPayload] = {}
    for occurrence in occurrences:
        existing = by_doc.get(occurrence.payload.doc_id)
        if (
            existing is not None
            and existing.payload_sha256 != occurrence.payload.payload_sha256
        ):
            raise ValueError(
                f"conflicting payload for doc_id {occurrence.payload.doc_id}"
            )
        by_doc[occurrence.payload.doc_id] = occurrence.payload
    payload_parts: list[dict] = []
    payload_paths: dict[str, str] = {}
    batches = _payload_batches(list(by_doc.values()), target_bytes)
    for index, batch in enumerate(batches, start=1):
        path = quarter_dir / f"payload-{index:05d}.parquet"
        table = pa.Table.from_pylist(
            [{"doc_id": row.doc_id, "clean_text": row.clean_text} for row in batch],
            schema=_payload_schema(),
        )
        write_table_atomic(
            table,
            path,
            expected_rows=len(batch),
            expected_schema=_payload_schema(),
            compression="zstd",
            row_group_size=5000,
        )
        relative = _path_for(artifact_root, path)
        for row in batch:
            payload_paths[row.doc_id] = relative
        payload_parts.append(
            _part(
                artifact_root,
                path,
                kind="payload",
                year=year,
                quarter=quarter,
                row_count=len(batch),
            )
        )
    index_rows = []
    for occurrence in sorted(occurrences, key=lambda item: item.row["occurrence_id"]):
        row = {
            **occurrence.row,
            "payload_file": payload_paths[occurrence.payload.doc_id],
        }
        index_rows.append(row)
    index_path = quarter_dir / "index.parquet"
    write_table_atomic(
        pa.Table.from_pylist(index_rows, schema=_index_schema()),
        index_path,
        expected_rows=len(index_rows),
        expected_schema=_index_schema(),
        compression="zstd",
        row_group_size=5000,
    )
    return [
        _part(
            artifact_root,
            index_path,
            kind="index",
            year=year,
            quarter=quarter,
            row_count=len(index_rows),
        ),
        *payload_parts,
    ]


def publish_projected_snapshot(
    partition_dbs: Iterable[str | Path],
    *,
    artifacts_root: str | Path,
    source_snapshot_ids: Iterable[str] = (),
    operation: str = "merge",
    target_bytes: int = 96 * 1024 * 1024,
    set_current: bool = True,
) -> dict:
    """Project finalized partition databases and publish a snapshot."""
    root = Path(artifacts_root).resolve()
    projected: list[ProjectedOccurrence] = []
    for path in partition_dbs:
        projected.extend(project_partition(path))
    occurrence_map: dict[str, ProjectedOccurrence] = {}
    for row in projected:
        previous = occurrence_map.get(str(row.row["occurrence_id"]))
        if previous is not None and previous.row != row.row:
            raise ValueError(f"conflicting occurrence {row.row['occurrence_id']}")
        occurrence_map[str(row.row["occurrence_id"])] = row
    projected = list(occurrence_map.values())
    grouped: dict[tuple[int, str], list[ProjectedOccurrence]] = defaultdict(list)
    doc_quarters: dict[str, tuple[int, str]] = {}
    for row in projected:
        prior_quarter = doc_quarters.get(row.payload.doc_id)
        current_quarter = (row.year, row.quarter)
        if prior_quarter is not None and prior_quarter != current_quarter:
            raise ValueError(f"doc_id {row.payload.doc_id} occurs in multiple quarters")
        doc_quarters[row.payload.doc_id] = current_quarter
        grouped[(row.year, row.quarter)].append(row)
    payloads = {row.payload.doc_id: row.payload for row in projected}
    logical = _logical_fingerprint(
        [row.row for row in projected], list(payloads.values())
    )
    physical_id = snapshot_id(
        operation=operation,
        source_snapshot_ids=source_snapshot_ids,
        artifact_hashes=[logical],
        schema_version=f"{SNAPSHOT_SCHEMA_VERSION}:{NORMALIZED_SCHEMA_VERSION}",
    )
    parts: list[dict] = []
    for (year, quarter), rows in sorted(grouped.items()):
        parts.extend(
            write_quarter_parts(
                root=root,
                snapshot=physical_id,
                year=year,
                quarter=quarter,
                occurrences=rows,
                target_bytes=target_bytes,
            )
        )
    manifest = make_snapshot_manifest(
        snapshot_id=physical_id,
        schema_version=f"{SNAPSHOT_SCHEMA_VERSION}:{NORMALIZED_SCHEMA_VERSION}",
        resolved_parts=parts,
        added_parts=parts,
        source_snapshot_ids=sorted(set(source_snapshot_ids)),
        dataset=DATASET,
        phase=PHASE,
        effective_cik_count=len(projected),
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
    "write_quarter_parts",
]
