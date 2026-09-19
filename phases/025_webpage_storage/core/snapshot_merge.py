"""Incremental snapshot publication from finalized Phase 2.5 partitions."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

import zstandard

from defs.runtime.artifacts import make_snapshot_manifest, publish_snapshot_manifest
from defs.sql import Select, Table, col, make_sql_executor
from defs.storage import canonical_json, pa, write_table_atomic

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
    _choose_normalized,
    _index_schema,
    _part,
    _payload_batches,
    _payload_schema,
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
    normalized = _choose_normalized(
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


def _write_delta_quarter(
    *,
    root: Path,
    snapshot: str,
    year: int,
    quarter: str,
    rows: list[ProjectedOccurrence],
    existing_doc_ids: set[str],
    target_bytes: int,
) -> list[dict]:
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
    payloads = {}
    for row in rows:
        if row.payload.doc_id not in existing_doc_ids:
            previous = payloads.get(row.payload.doc_id)
            if previous and previous.payload_sha256 != row.payload.payload_sha256:
                raise ValueError(f"conflicting payload for doc_id {row.payload.doc_id}")
            payloads[row.payload.doc_id] = row.payload
    new_payloads = list(payloads.values())
    parts: list[dict] = []
    payload_paths: dict[str, str] = {}
    for index, batch in enumerate(
        _payload_batches(new_payloads, target_bytes), start=1
    ):
        path = quarter_dir / f"payload-{index:05d}.parquet"
        table = pa.Table.from_pylist(
            [{"doc_id": item.doc_id, "clean_text": item.clean_text} for item in batch],
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
        relative = path.resolve().relative_to(root.resolve()).as_posix()
        for item in batch:
            payload_paths[item.doc_id] = relative
        parts.append(
            _part(
                root,
                path,
                kind="payload",
                year=year,
                quarter=quarter,
                row_count=len(batch),
            )
        )
    index_rows = []
    for row in sorted(rows, key=lambda item: str(item.row["occurrence_id"])):
        value = dict(row.row)
        if "payload_file" not in value:
            value["payload_file"] = payload_paths[row.payload.doc_id]
        index_rows.append(value)
    index_path = quarter_dir / "index.parquet"
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
    return parts


def merge_partitions_to_snapshot(
    partition_dbs: Iterable[str | Path],
    *,
    artifacts_root: str | Path,
    base_snapshot_id: str | None = None,
    target_bytes: int = 96 * 1024 * 1024,
    set_current: bool = True,
) -> dict:
    """Publish a layered snapshot from finalized partition databases."""
    root = Path(artifacts_root).resolve()
    reader = SnapshotReader(root, base_snapshot_id) if base_snapshot_id else None
    projected: list[ProjectedOccurrence] = []
    for path in partition_dbs:
        projected.extend(project_incremental_partition(path, reader))
    by_occurrence: dict[str, ProjectedOccurrence] = {}
    for row in projected:
        key = str(row.row["occurrence_id"])
        prior = by_occurrence.get(key)
        if prior is not None and prior.row != row.row:
            raise ValueError(f"conflicting occurrence {key}")
        by_occurrence[key] = row
    projected = list(by_occurrence.values())
    if reader is None:
        return publish_projected_snapshot(
            partition_dbs,
            artifacts_root=root,
            target_bytes=target_bytes,
            set_current=set_current,
        )
    existing_rows = reader.index_rows()
    existing_by_occurrence = {str(row["occurrence_id"]): row for row in existing_rows}
    filtered_projected: list[ProjectedOccurrence] = []
    for row in projected:
        existing = existing_by_occurrence.get(str(row.row["occurrence_id"]))
        if existing is None:
            filtered_projected.append(row)
            continue
        comparable = {
            key: value for key, value in existing.items() if key != "payload_file"
        }
        if comparable != row.row:
            raise ValueError(f"conflicting occurrence {row.row['occurrence_id']}")
    projected = filtered_projected
    if not projected:
        return reader.manifest
    existing_doc_ids = {str(row["doc_id"]) for row in existing_rows}
    existing_doc_quarters: dict[str, set[tuple[int, str]]] = defaultdict(set)
    for existing in existing_rows:
        existing_doc_quarters[str(existing["doc_id"])].add(
            filing_quarter(existing["filing_date"])
        )
    for row in projected:
        if row.payload.doc_id in existing_doc_ids:
            quarters = existing_doc_quarters[row.payload.doc_id]
            if quarters and (row.year, row.quarter) not in quarters:
                raise ValueError(
                    f"doc_id {row.payload.doc_id} occurs in multiple quarters"
                )
    grouped: dict[tuple[int, str], list[ProjectedOccurrence]] = defaultdict(list)
    for row in projected:
        grouped[(row.year, row.quarter)].append(row)
    delta_digest = hashlib.sha256(
        canonical_json(
            {
                "occurrences": sorted(
                    (row.row for row in projected),
                    key=lambda value: str(value["occurrence_id"]),
                ),
                "payloads": sorted(
                    {
                        "doc_id": row.payload.doc_id,
                        "payload_sha256": row.payload.payload_sha256,
                    }
                    for row in projected
                    if row.payload.doc_id not in existing_doc_ids
                ),
            }
        ).encode("utf-8")
    ).hexdigest()
    physical_id = snapshot_id(
        operation="merge",
        source_snapshot_ids=[reader.snapshot_id],
        artifact_hashes=[delta_digest],
        schema_version=reader.manifest["schema_version"],
    )
    new_parts: list[dict] = []
    for (year, quarter), rows in sorted(grouped.items()):
        new_parts.extend(
            _write_delta_quarter(
                root=root,
                snapshot=physical_id,
                year=year,
                quarter=quarter,
                rows=rows,
                existing_doc_ids=existing_doc_ids,
                target_bytes=target_bytes,
            )
        )
    inherited = list(reader.manifest.get("resolved_parts", []))
    paths = {str(part["path"]) for part in inherited}
    resolved = inherited + [part for part in new_parts if part["path"] not in paths]
    manifest = make_snapshot_manifest(
        snapshot_id=physical_id,
        schema_version=reader.manifest["schema_version"],
        resolved_parts=resolved,
        added_parts=new_parts,
        parent_snapshot_id=reader.snapshot_id,
        source_snapshot_ids=[reader.snapshot_id],
        dataset=DATASET,
        phase=PHASE,
        effective_cik_count=len(existing_rows) + len(projected),
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
    publish_snapshot_manifest(
        manifest,
        artifacts_root=root,
        phase=PHASE,
        dataset=DATASET,
        set_current=set_current,
    )
    return manifest


__all__ = ["merge_partitions_to_snapshot", "project_incremental_partition"]
