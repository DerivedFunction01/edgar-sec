"""Incremental snapshot publication from finalized Phase 2.5 partitions."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

from defs.runtime.artifacts import make_snapshot_manifest, publish_snapshot_manifest
from defs.sql import make_sql_executor
from defs.storage import (
    FinalizedDataset,
    canonical_json,
    file_sha256,
    force_reclaim_memory,
)

from .partition_reader import PartitionBatchReader
from .queries import relation_key_rows
from .snapshot import (
    DATASET,
    PHASE,
    SnapshotReader,
    _materialize_planned_parts,
    _path_for,
    _project_index_row,
    _write_quarter_index_part,
    filing_quarter,
    plan_payload_parts,
    publish_projected_snapshot,
    snapshot_id,
)


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


def _plan_delta_rows(
    partition_dbs: list[Path],
    *,
    index_relation: str,
    payload_relation: str,
    lookup,
    batch_size: int,
    threads: int | None,
    memory_limit: str | None,
    temp_directory: str | Path | None,
    progress,
) -> tuple[
    dict[str, dict],
    dict[str, tuple[int, str]],
    dict[str, dict],
    dict[tuple[int, str], list[tuple[str, int]]],
    int,
    str,
]:
    """Pass 1: metadata-only scan with bounded base lookups; no blob reads."""
    delta_rows: dict[str, dict] = {}
    delta_quarters: dict[str, tuple[int, str]] = {}
    doc_meta: dict[str, dict] = {}
    doc_sizes: dict[tuple[int, str], list[tuple[str, int]]] = defaultdict(list)
    seen_occurrences: set[str] = set()
    new_count = 0
    delta_hasher = hashlib.sha256()
    try:
        for partition_index, partition_db in enumerate(partition_dbs, start=1):
            if progress:
                progress({"type": "partition_started", "partition_id": partition_index})
            partition_rows = 0
            with PartitionBatchReader(
                partition_db,
                threads=threads,
                memory_limit=memory_limit,
                temp_directory=temp_directory,
            ) as source:
                for raw_batch in source.iter_rows(
                    batch_size=max(1, batch_size),
                    include_missing=True,
                    with_payload=False,
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
                    for raw in raw_batch:
                        occurrence_id = str(raw["occurrence_id"])
                        doc_id = str(raw["doc_id"])
                        existing = base_rows.get(occurrence_id)
                        if existing is not None:
                            if "payload_sha256" in raw:
                                projected = _project_index_row(raw)
                                comparable = {
                                    key: value
                                    for key, value in existing.items()
                                    if key != "payload_file"
                                }
                                if comparable != projected:
                                    raise ValueError(
                                        f"conflicting occurrence {occurrence_id}"
                                    )
                                base_payload = base_payloads.get(doc_id)
                                if base_payload is None:
                                    raise ValueError(
                                        f"missing base payload for doc_id {doc_id}"
                                    )
                                if (
                                    str(raw["payload_sha256"])
                                    != hashlib.sha256(
                                        str(base_payload["clean_text"]).encode("utf-8")
                                    ).hexdigest()
                                ):
                                    raise ValueError(
                                        f"conflicting normalized content for doc_id {doc_id}"
                                    )
                            continue
                        if occurrence_id in seen_occurrences:
                            raise ValueError(f"duplicate occurrence {occurrence_id}")
                        seen_occurrences.add(occurrence_id)
                        year, quarter = filing_quarter(raw["filing_date"])
                        base_doc = base_docs.get(doc_id)
                        if base_doc is not None and filing_quarter(
                            base_doc["filing_date"]
                        ) != (year, quarter):
                            raise ValueError(
                                f"doc_id {doc_id} occurs in multiple quarters"
                            )
                        if "payload_sha256" in raw:
                            row = _project_index_row(raw)
                            payload_sha = str(raw["payload_sha256"])
                            if base_doc is not None:
                                base_payload = base_payloads.get(doc_id)
                                if base_payload is None:
                                    raise ValueError(
                                        f"missing base payload for doc_id {doc_id}"
                                    )
                                if (
                                    payload_sha
                                    != hashlib.sha256(
                                        str(base_payload["clean_text"]).encode("utf-8")
                                    ).hexdigest()
                                ):
                                    raise ValueError(
                                        f"conflicting normalized content for doc_id {doc_id}"
                                    )
                                row["payload_file"] = str(base_doc["payload_file"])
                            else:
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
                                    raise ValueError(
                                        f"conflicting payload for doc_id {doc_id}"
                                    )
                        else:
                            if base_doc is None or doc_id not in base_payloads:
                                continue
                            row = {
                                "occurrence_id": occurrence_id,
                                "source_cik": str(raw["source_cik"]),
                                "accession": str(raw["accession"]),
                                "form": str(raw["form"]),
                                "filing_date": str(raw["filing_date"])[:10],
                                "report_date": None
                                if raw["report_date"] is None
                                else str(raw["report_date"])[:10],
                                "document_path": str(raw["document_path"]),
                                "doc_id": doc_id,
                                "mime_type": str(base_doc["mime_type"]),
                                "byte_size": int(base_doc["byte_size"]),
                                "payload_file": str(base_doc["payload_file"]),
                            }
                            payload_sha = hashlib.sha256(
                                str(base_payloads[doc_id]["clean_text"]).encode("utf-8")
                            ).hexdigest()
                        delta_rows[occurrence_id] = row
                        delta_quarters[occurrence_id] = (year, quarter)
                        new_count += 1
                        delta_hasher.update(
                            canonical_json(
                                {
                                    "index": {
                                        key: value
                                        for key, value in row.items()
                                        if key != "payload_file"
                                    },
                                    "payload_sha256": payload_sha,
                                }
                            ).encode("utf-8")
                        )
                    partition_rows += len(raw_batch)
                    del raw_batch
                    force_reclaim_memory()
            if progress:
                progress(
                    {
                        "type": "partition_done",
                        "partition_id": partition_index,
                        "rows": partition_rows,
                    }
                )
    finally:
        lookup.close()
    return (
        delta_rows,
        delta_quarters,
        doc_meta,
        doc_sizes,
        new_count,
        delta_hasher.hexdigest(),
    )


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
    (
        delta_rows,
        delta_quarters,
        doc_meta,
        doc_sizes,
        new_count,
        delta_digest,
    ) = _plan_delta_rows(
        partition_dbs,
        index_relation=index_relation,
        payload_relation=payload_relation,
        lookup=lookup,
        batch_size=batch_size,
        threads=threads,
        memory_limit=memory_limit,
        temp_directory=temp_directory,
        progress=progress,
    )
    if not delta_rows:
        return reader.manifest

    # Pass 1.5: plan new payload parts; inherited rows already carry payload_file.
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
    for row in delta_rows.values():
        if "payload_file" not in row:
            row["payload_file"] = doc_payload_file[row["doc_id"]]

    # Pass 2: materialize one planned payload part at a time.
    parts = _materialize_planned_parts(
        planned_parts,
        root=root,
        partition_paths=partition_dbs,
        doc_meta=doc_meta,
        target_bytes=target_bytes,
        batch_size=batch_size,
        threads=threads,
        memory_limit=memory_limit,
        temp_directory=temp_directory,
        progress=progress,
    )
    quarter_groups: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for occurrence_id, row in delta_rows.items():
        quarter_groups[delta_quarters[occurrence_id]].append(row)
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
                "rows": new_count,
                "payloads": len(doc_meta),
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
    batch_size: int = 4096,
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


__all__ = ["merge_partitions_to_snapshot"]
