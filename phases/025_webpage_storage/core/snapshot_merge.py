"""Incremental snapshot publication from finalized Phase 2.5 partitions."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

import zstandard

from defs.runtime.artifacts import make_snapshot_manifest, publish_snapshot_manifest
from defs.sql import Select, Table, col, make_sql_executor
from defs.storage import (
    FinalizedDataset,
    canonical_json,
    file_sha256,
    force_reclaim_memory,
)

from .partition_reader import PartitionBatchReader, choose_normalized
from .queries import relation_key_rows
from .schemas import (
    FILING_OCCURRENCES_TABLE,
    NORMALIZED_DOCUMENTS_TABLE,
    decompress_payload,
)
from .snapshot import (
    DATASET,
    PHASE,
    NormalizedPayload,
    ProjectedOccurrence,
    SnapshotReader,
    _project_source_row,
    _write_projected_quarter_batch,
    filing_quarter,
    publish_projected_snapshot,
    snapshot_id,
)


def _rows(path: Path, table: str, columns: tuple[str, ...]) -> list[dict]:
    executor = make_sql_executor(path, dialect="sqlite")
    try:
        query = Select(
            source=Table(table),
            projection=tuple(col(column) for column in columns),
        )
        return executor.query(executor.compiler.compile(query))
    finally:
        executor.close()


def _normalized_payload(row: dict) -> tuple[str, str]:
    compressed = bytes(row["normalized_payload"])
    try:
        clean_bytes = decompress_payload(compressed)
    except zstandard.ZstdError:
        clean_bytes = compressed
    return clean_bytes.decode("utf-8", errors="replace").replace("\x00", ""), str(
        row["payload_sha256"]
    )


def project_incremental_partition(
    partition_db: str | Path,
    base_reader: SnapshotReader | None,
) -> list[ProjectedOccurrence]:
    """Project new and occurrence-only rows against an optional base snapshot."""
    path = Path(partition_db)
    occurrences = _rows(
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
    normalized = choose_normalized(
        _rows(
            path,
            NORMALIZED_DOCUMENTS_TABLE,
            (
                "source_doc_id",
                "byte_size",
                "normalized_payload",
                "payload_sha256",
                "mime_type",
            ),
        )
    )
    base_rows = base_reader.index_rows() if base_reader else []
    base_by_doc = {str(row["doc_id"]): row for row in base_rows}
    base_payloads = (
        {str(row["doc_id"]): row for row in base_reader.payload_rows(base_rows)}
        if base_reader
        else {}
    )
    result: list[ProjectedOccurrence] = []
    for occurrence in occurrences:
        doc_id = str(occurrence["doc_id"])
        normalized_row = normalized.get(doc_id)
        existing = base_by_doc.get(doc_id)
        if normalized_row is not None:
            clean_text, payload_sha256 = _normalized_payload(normalized_row)
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
            if existing is not None:
                current_payload = base_payloads.get(doc_id)
                if current_payload is None:
                    continue
                current_hash = hashlib.sha256(
                    str(current_payload["clean_text"]).encode("utf-8")
                ).hexdigest()
                if current_hash != payload_sha256:
                    raise ValueError(
                        f"conflicting normalized content for doc_id {doc_id}"
                    )
                index_row["payload_file"] = existing["payload_file"]
            payload = NormalizedPayload(doc_id, clean_text, payload_sha256)
        elif existing is not None and doc_id in base_payloads:
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
                "mime_type": existing["mime_type"],
                "byte_size": existing["byte_size"],
            }
            index_row["payload_file"] = existing["payload_file"]
            clean_text = str(base_payloads[doc_id]["clean_text"])
            payload = NormalizedPayload(
                doc_id,
                clean_text,
                hashlib.sha256(clean_text.encode("utf-8")).hexdigest(),
            )
        else:
            continue
        year, quarter = filing_quarter(occurrence["filing_date"])
        result.append(ProjectedOccurrence(index_row, payload, year, quarter))
    return result


def _manifest_relation(root: Path, reader: SnapshotReader, kind: str) -> str:
    parts = [
        part
        for part in reader.manifest.get("resolved_parts", [])
        if part.get("kind") == kind
    ]
    if not parts:
        raise ValueError(f"base snapshot contains no {kind} parts")
    dataset = FinalizedDataset({"resolved_parts": parts}, artifacts_root=root)
    try:
        return dataset.relation
    finally:
        dataset.close()


def _bounded_base_rows(
    executor,
    index_relation: str,
    payload_relation: str,
    occurrence_ids: tuple[str, ...],
    doc_ids: tuple[str, ...],
) -> tuple[dict[str, dict], dict[str, dict]]:
    columns = (
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
    index_rows = {
        str(row["occurrence_id"]): row
        for batch in relation_key_rows(
            executor,
            index_relation,
            columns,
            key_column="occurrence_id",
            keys=occurrence_ids,
            batch_size=max(1, len(occurrence_ids)),
        )
        for row in batch
    }
    for batch in relation_key_rows(
        executor,
        index_relation,
        columns,
        key_column="doc_id",
        keys=doc_ids,
        batch_size=max(1, len(doc_ids)),
    ):
        for row in batch:
            index_rows[str(row["occurrence_id"])] = row
    matching_doc_ids = tuple(
        sorted({str(row["doc_id"]) for row in index_rows.values()})
    )
    if not matching_doc_ids:
        return index_rows, {}
    payload_batches = relation_key_rows(
        executor,
        payload_relation,
        ("doc_id", "clean_text"),
        key_column="doc_id",
        keys=matching_doc_ids,
        batch_size=max(1, len(matching_doc_ids)),
    )
    payload_rows = {
        str(row["doc_id"]): row for batch in payload_batches for row in batch
    }
    return index_rows, payload_rows


def _merge_incremental_bounded(
    partition_dbs: list[Path],
    *,
    root: Path,
    reader: SnapshotReader,
    target_bytes: int,
    batch_size: int,
    threads: int | None,
    memory_limit: str | None,
    temp_directory: str | Path | None,
    set_current: bool,
    progress,
) -> dict:
    index_relation = _manifest_relation(root, reader, "index")
    payload_relation = _manifest_relation(root, reader, "payload")
    lookup = make_sql_executor(
        dialect="duckdb",
        threads=threads,
        memory_limit=memory_limit,
        temp_directory=temp_directory,
    )
    physical_id = snapshot_id(
        operation="merge",
        source_snapshot_ids=[reader.snapshot_id],
        artifact_hashes=[file_sha256(path) for path in partition_dbs],
        schema_version=str(reader.manifest["schema_version"]),
    )
    parts: list[dict] = []
    payload_paths: dict[str, str] = {}
    payload_hashes: dict[str, str] = {}
    payload_sequences: dict[tuple[int, str], int] = defaultdict(int)
    index_sequences: dict[tuple[int, str], int] = defaultdict(int)
    seen_occurrences: set[str] = set()
    new_count = 0
    payload_count = 0
    delta_hasher = hashlib.sha256()
    try:
        for partition_index, partition_db in enumerate(partition_dbs, start=1):
            if progress:
                progress({"type": "partition_started", "partition_id": partition_index})
            with PartitionBatchReader(
                partition_db,
                threads=threads,
                memory_limit=memory_limit,
                temp_directory=temp_directory,
            ) as source:
                for raw_batch in source.iter_rows(
                    batch_size=max(1, batch_size), include_missing=True
                ):
                    occurrence_ids = tuple(
                        str(row["occurrence_id"]) for row in raw_batch
                    )
                    doc_ids = tuple(str(row["doc_id"]) for row in raw_batch)
                    base_rows, base_payloads = _bounded_base_rows(
                        lookup,
                        index_relation,
                        payload_relation,
                        occurrence_ids,
                        doc_ids,
                    )
                    base_docs = {str(row["doc_id"]): row for row in base_rows.values()}
                    grouped: dict[tuple[int, str], list[ProjectedOccurrence]] = (
                        defaultdict(list)
                    )
                    for raw in raw_batch:
                        occurrence_id = str(raw["occurrence_id"])
                        existing = base_rows.get(occurrence_id)
                        if existing is not None:
                            if "normalized_payload" in raw:
                                projected = _project_source_row(raw)
                                comparable = {
                                    key: value
                                    for key, value in existing.items()
                                    if key != "payload_file"
                                }
                                if comparable != projected.row:
                                    raise ValueError(
                                        f"conflicting occurrence {occurrence_id}"
                                    )
                                base_payload = base_payloads.get(str(raw["doc_id"]))
                                if base_payload is None:
                                    raise ValueError(
                                        f"missing base payload for doc_id {raw['doc_id']}"
                                    )
                                if (
                                    hashlib.sha256(
                                        projected.payload.clean_text.encode("utf-8")
                                    ).hexdigest()
                                    != hashlib.sha256(
                                        str(base_payload["clean_text"]).encode("utf-8")
                                    ).hexdigest()
                                ):
                                    raise ValueError(
                                        f"conflicting normalized content for doc_id {raw['doc_id']}"
                                    )
                            continue
                        if occurrence_id in seen_occurrences:
                            raise ValueError(f"duplicate occurrence {occurrence_id}")
                        seen_occurrences.add(occurrence_id)
                        base_doc = base_docs.get(str(raw["doc_id"]))
                        base_payload = base_payloads.get(str(raw["doc_id"]))
                        if "normalized_payload" in raw:
                            projected = _project_source_row(raw)
                        elif base_doc is not None and base_payload is not None:
                            clean_text = str(base_payload["clean_text"])
                            payload = NormalizedPayload(
                                str(raw["doc_id"]),
                                clean_text,
                                hashlib.sha256(clean_text.encode("utf-8")).hexdigest(),
                            )
                            year, quarter = filing_quarter(raw["filing_date"])
                            projected = ProjectedOccurrence(
                                {
                                    "occurrence_id": occurrence_id,
                                    "source_cik": str(raw["source_cik"]),
                                    "accession": str(raw["accession"]),
                                    "form": str(raw["form"]),
                                    "filing_date": str(raw["filing_date"])[:10],
                                    "report_date": None
                                    if raw["report_date"] is None
                                    else str(raw["report_date"])[:10],
                                    "document_path": str(raw["document_path"]),
                                    "doc_id": str(raw["doc_id"]),
                                    "mime_type": str(base_doc["mime_type"]),
                                    "byte_size": int(base_doc["byte_size"]),
                                },
                                payload,
                                year,
                                quarter,
                            )
                        else:
                            continue
                        if base_doc is not None and base_payload is not None:
                            projected = ProjectedOccurrence(
                                {
                                    **projected.row,
                                    "payload_file": base_doc["payload_file"],
                                },
                                NormalizedPayload(
                                    projected.payload.doc_id,
                                    str(base_payload["clean_text"]),
                                    hashlib.sha256(
                                        str(base_payload["clean_text"]).encode("utf-8")
                                    ).hexdigest(),
                                ),
                                projected.year,
                                projected.quarter,
                            )
                            payload_paths[projected.payload.doc_id] = str(
                                base_doc["payload_file"]
                            )
                            payload_hashes[projected.payload.doc_id] = (
                                projected.payload.payload_sha256
                            )
                        delta_hasher.update(
                            canonical_json(
                                {
                                    "index": projected.row,
                                    "payload_sha256": projected.payload.payload_sha256,
                                }
                            ).encode("utf-8")
                        )
                        grouped[(projected.year, projected.quarter)].append(projected)
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
                        new_count += len(rows)
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
                    force_reclaim_memory()
            if progress:
                progress({"type": "partition_done", "partition_id": partition_index})
    finally:
        lookup.close()
    if not new_count:
        return reader.manifest
    delta_digest = delta_hasher.hexdigest()
    inherited = list(reader.manifest.get("resolved_parts", []))
    paths = {str(part["path"]) for part in inherited}
    resolved = inherited + [part for part in parts if part["path"] not in paths]
    manifest = make_snapshot_manifest(
        snapshot_id=physical_id,
        schema_version=reader.manifest["schema_version"],
        resolved_parts=resolved,
        added_parts=parts,
        parent_snapshot_id=reader.snapshot_id,
        source_snapshot_ids=[reader.snapshot_id],
        dataset=DATASET,
        phase=PHASE,
        effective_cik_count=int(reader.manifest.get("effective_cik_count", 0))
        + new_count,
        effective_input_fingerprint=delta_digest,
        provenance={"operation": "merge", "delta_fingerprint": delta_digest},
    )
    manifest["logical_fingerprint"] = hashlib.sha256(
        canonical_json(
            {
                "parent": reader.manifest.get("logical_fingerprint"),
                "delta": delta_digest,
            }
        ).encode("utf-8")
    ).hexdigest()
    manifest["effective_payload_count"] = payload_count
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
                "rows": new_count,
                "payloads": payload_count,
            }
        )
    return manifest


def merge_partitions_to_snapshot(
    partition_dbs: Iterable[str | Path],
    *,
    artifacts_root: str | Path,
    base_snapshot_id: str | None = None,
    target_bytes: int = 96 * 1024 * 1024,
    set_current: bool = True,
    batch_size: int = 512,
    threads: int | None = None,
    memory_limit: str | None = None,
    temp_directory: str | Path | None = None,
    progress=None,
) -> dict:
    """Publish a layered snapshot from finalized partition databases."""
    root = Path(artifacts_root).resolve()
    reader = SnapshotReader(root, base_snapshot_id) if base_snapshot_id else None
    if reader is None:
        return publish_projected_snapshot(
            partition_dbs,
            artifacts_root=root,
            target_bytes=target_bytes,
            set_current=set_current,
            batch_size=batch_size,
            threads=threads,
            memory_limit=memory_limit,
            temp_directory=temp_directory,
            progress=progress,
        )
    return _merge_incremental_bounded(
        [Path(path) for path in partition_dbs],
        root=root,
        reader=reader,
        target_bytes=target_bytes,
        batch_size=batch_size,
        threads=threads,
        memory_limit=memory_limit,
        temp_directory=temp_directory,
        set_current=set_current,
        progress=progress,
    )


__all__ = ["merge_partitions_to_snapshot", "project_incremental_partition"]
