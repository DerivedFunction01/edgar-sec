"""Parquet schema and IO for chunk checkpoints — the worker's resumability record.

The merger validates this schema; the worker reuses checkpoints written against it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.domain.document.models import (
    FilingOccurrence,
    RawDocumentBlob,
    derive_document_locator_key,
)
from edgar_sec.infra.storage.parquet import StagedParquetWriter

DOCUMENT_SNAPSHOT_SCHEMA = pa.schema(
    [
        ("occurrence_id", pa.string()),
        ("source_cik", pa.string()),
        ("accession", pa.string()),
        ("document_path", pa.string()),
        ("document_locator_key", pa.string()),
        ("blob_hash", pa.string()),
        # Carried from the occurrence, not derived: a stored document without its form
        # and filing date cannot be repartitioned into fiscal quarters at consolidation.
        ("form", pa.string()),
        ("filing_date", pa.string()),
        ("raw_payload", pa.binary()),
        ("byte_size", pa.int64()),
        ("normalized_text", pa.string()),
        ("status", pa.string()),
        ("error_message", pa.string()),
    ]
)


def write_chunk_snapshot(
    output_path: Path | str,
    occurrences: Sequence[FilingOccurrence],
    raw_blobs: Mapping[str, bytes | RawDocumentBlob],
    normalized_texts: Mapping[str, str],
    statuses: Mapping[str, str] | None = None,
    error_messages: Mapping[str, str | None] | None = None,
) -> Path:
    """Serialize worker chunk records directly to an atomic Parquet snapshot file."""
    dest = Path(output_path).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)

    occurrence_ids: list[str] = []
    source_ciks: list[str] = []
    accessions: list[str] = []
    document_paths: list[str] = []
    document_locator_keys: list[str] = []
    blob_hashes: list[str] = []
    forms: list[str] = []
    filing_dates: list[str] = []
    raw_payloads: list[bytes] = []
    byte_sizes: list[int] = []
    norm_texts: list[str] = []
    status_list: list[str] = []
    error_list: list[str | None] = []

    for occ in occurrences:
        occurrence_ids.append(occ.occurrence_id)
        source_ciks.append(occ.source_cik.to_10digit())
        accessions.append(str(occ.accession))
        document_paths.append(occ.document_path)
        doc_key = derive_document_locator_key(str(occ.accession), occ.document_path)
        document_locator_keys.append(doc_key)
        blob_hash = occ.doc_id
        blob_hashes.append(blob_hash)

        raw_item = raw_blobs.get(blob_hash)
        if isinstance(raw_item, bytes):
            raw_payload = raw_item
            byte_size = len(raw_payload)
        elif raw_item is not None:
            raw_payload = getattr(raw_item, "raw_payload", b"")
            byte_size = getattr(raw_item, "byte_size", len(raw_payload))
        else:
            raw_payload = b""
            byte_size = 0

        forms.append(occ.form)
        filing_dates.append(occ.filing_date)
        raw_payloads.append(raw_payload)
        byte_sizes.append(byte_size)

        norm_texts.append(normalized_texts.get(occ.occurrence_id, ""))
        status = statuses.get(occ.occurrence_id, "ok") if statuses else "ok"
        status_list.append(status)
        err = error_messages.get(occ.occurrence_id) if error_messages else None
        error_list.append(err)

    data = {
        "occurrence_id": occurrence_ids,
        "source_cik": source_ciks,
        "accession": accessions,
        "document_path": document_paths,
        "document_locator_key": document_locator_keys,
        "blob_hash": blob_hashes,
        "form": forms,
        "filing_date": filing_dates,
        "raw_payload": raw_payloads,
        "byte_size": byte_sizes,
        "normalized_text": norm_texts,
        "status": status_list,
        "error_message": error_list,
    }

    with StagedParquetWriter(
        dest,
        schema=DOCUMENT_SNAPSHOT_SCHEMA,
        id_column="occurrence_id",
    ) as writer:
        writer.write_batch(data)
        writer.commit(expected_count=len(occurrences))

    return dest


def validate_chunk_snapshot(parquet_path: Path | str) -> dict[str, Any]:
    """Validate a chunk Parquet file against the snapshot schema contract."""
    path = Path(parquet_path)
    if not path.is_file():
        raise FileNotFoundError(f"chunk parquet file not found: {path}")

    meta = pq.read_metadata(path)
    schema = pq.read_schema(path)

    expected_names = DOCUMENT_SNAPSHOT_SCHEMA.names
    actual_names = schema.names
    if actual_names != expected_names:
        raise ValueError(
            f"chunk schema mismatch in {path}: expected {expected_names}, got {actual_names}"
        )

    return {
        "path": str(path),
        "num_rows": meta.num_rows,
        "num_row_groups": meta.num_row_groups,
        "serialized_size_bytes": path.stat().st_size,
    }


__all__ = [
    "DOCUMENT_SNAPSHOT_SCHEMA",
    "validate_chunk_snapshot",
    "write_chunk_snapshot",
]
