"""Parquet schema and IO for chunk checkpoints — the worker's resumability record.

The merger validates this schema; the worker reuses checkpoints written against it.
Checkpoint validity is validated by the file, and chunk reuse additionally requires
that the checkpoint be stamped by the processor being asked to run now.
"""

from __future__ import annotations

import json
import logging
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
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.atomic import atomic_write_json, atomic_write_text
from edgar_sec.infra.storage.parquet import StagedParquetWriter
from edgar_sec.pipelines.document_storage.paths import (
    catalog_delegation_path,
    chunk_checkpoint_path,
)
from edgar_sec.pipelines.document_storage.work_order import DelegationTarget

log = logging.getLogger("document_storage.checkpoint")

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
        # Per-occurrence resolution/storage metadata: document_role,
        # parent_locator_key, document_path_source, and resolution_outcome,
        # canonical JSON-encoded and defaulting to "{}". Not ProcessedDocument
        # metadata; it comes from the resolution/worker context.
        ("metadata", pa.string()),
        # Carried from the occurrence: the filing's report date, distinct from
        # filing_date and nullable when the catalog did not publish one.
        ("report_date", pa.string()),
    ]
)


def _validate_metadata(metadata_map: Mapping[str, str]) -> None:
    """Validate per-occurrence metadata before writing.

    Metadata must be parseable as JSON so invalid encoding is caught at write time
    rather than discovered in an immutable snapshot.
    """
    for occurrence_id, value in metadata_map.items():
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"invalid canonical JSON metadata for occurrence {occurrence_id!r}: {exc}"
            )
        if canonical_json(decoded) != value:
            raise ValueError(
                f"metadata for occurrence {occurrence_id!r} is not canonical JSON"
            )


def write_chunk_snapshot(
    output_path: Path | str,
    occurrences: Sequence[FilingOccurrence],
    raw_blobs: Mapping[str, bytes | RawDocumentBlob],
    normalized_texts: Mapping[str, str],
    statuses: Mapping[str, str] | None = None,
    error_messages: Mapping[str, str | None] | None = None,
    metadata_map: Mapping[str, str] | None = None,
    report_dates: Mapping[str, str | None] | None = None,
) -> Path:
    """Serialize worker chunk records directly to an atomic Parquet snapshot file."""
    dest = Path(output_path).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)

    metadata_map = metadata_map or {}
    report_dates = report_dates or {}
    _validate_metadata(metadata_map)

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
    report_date_list: list[str | None] = []
    metadata_list: list[str] = []

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

        report_date_list.append(report_dates.get(occ.occurrence_id, occ.report_date))
        metadata_list.append(metadata_map.get(occ.occurrence_id, "{}"))

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
        "report_date": report_date_list,
        "metadata": metadata_list,
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


def is_chunk_complete(
    chunks_dir: Path,
    chunk_id: str,
    *,
    processor_fingerprint: str,
) -> bool:
    """Return whether a chunk validates and was written by the current processor.

    Another processor's chunk is not reusable: mixing two text conventions into one
    snapshot is worse than recomputing.
    """
    path = chunk_checkpoint_path(chunks_dir, chunk_id)
    if not path.is_file():
        return False
    try:
        validate_chunk_snapshot(path)
    except (ValueError, FileNotFoundError, OSError) as exc:
        log.info("chunk %s checkpoint is unusable: %s", chunk_id, exc)
        return False
    return _fingerprint_matches(path, processor_fingerprint)


def _fingerprint_matches(path: Path, expected: str) -> bool:
    """Whether the processor stamped on a checkpoint matches the expectation."""
    return chunk_fingerprint(path) == expected


def chunk_fingerprint(path: Path) -> str | None:
    """Read the processor fingerprint stamped on a checkpoint, if any."""
    sidecar = Path(path).with_suffix(".fingerprint")
    if not sidecar.is_file():
        return None
    return sidecar.read_text(encoding="utf-8").strip() or None


def _stamp_fingerprint(path: Path, fingerprint: str) -> None:
    """Record the producing processor beside the checkpoint, not in its schema.

    Without it a completed chunk cannot be matched against the processor reusing it.
    """
    sidecar = path.with_suffix(".fingerprint")
    atomic_write_text(sidecar, fingerprint)


def _valid_partial_checkpoint(path: Path, processor_fingerprint: str) -> bool:
    """Whether a staging file plus its fingerprint can support resumption."""
    partial = path.with_name(f"{path.name}.tmp")
    fingerprint = path.with_name(f"{path.name}.tmp.fingerprint")
    if not partial.is_file() or not fingerprint.is_file():
        return False
    try:
        validate_chunk_snapshot(partial)
        return fingerprint.read_text(encoding="utf-8").strip() == processor_fingerprint
    except (OSError, ValueError):
        return False


def read_catalog_delegations(
    checkpoint: Path, chunk_id: str, processor_fingerprint: str
) -> tuple[DelegationTarget, ...] | None:
    """Read delegation targets only from a matching committed catalog checkpoint."""
    sidecar = catalog_delegation_path(checkpoint)
    try:
        stored = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (
        not isinstance(stored, dict)
        or stored.get("version") != 1
        or stored.get("chunk_id") != chunk_id
        or stored.get("processor_fingerprint") != processor_fingerprint
        or not isinstance(stored.get("delegations"), list)
    ):
        return None
    rows = stored["delegations"]
    if any(not isinstance(row, dict) for row in rows):
        return None
    try:
        return tuple(
            DelegationTarget(
                document_locator_key=str(row["document_locator_key"]),
                document_path=str(row["document_path"]),
                target_exhibit=str(row["target_exhibit"]),
            )
            for row in rows
        )
    except (KeyError, TypeError):
        return None


def _read_delegations(path: Path) -> list[DelegationTarget] | None:
    """Read a transient delegation list, tolerant of partial writes."""
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(stored, list):
            return None
        return [
            DelegationTarget(
                document_locator_key=str(row["document_locator_key"]),
                document_path=str(row["document_path"]),
                target_exhibit=str(row["target_exhibit"]),
            )
            for row in stored
            if isinstance(row, dict)
        ]
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return None


def _write_catalog_delegations(
    checkpoint: Path,
    chunk_id: str,
    processor_fingerprint: str,
    delegations: Sequence[DelegationTarget],
) -> None:
    """Atomically persist a checkpoint's delegation targets for the catalog pass."""
    atomic_write_json(
        catalog_delegation_path(checkpoint),
        {
            "version": 1,
            "chunk_id": chunk_id,
            "processor_fingerprint": processor_fingerprint,
            "delegations": [
                {
                    "document_locator_key": target.document_locator_key,
                    "document_path": target.document_path,
                    "target_exhibit": target.target_exhibit,
                }
                for target in delegations
            ],
        },
        canonical=True,
    )


__all__ = [
    "DOCUMENT_SNAPSHOT_SCHEMA",
    "validate_chunk_snapshot",
    "write_chunk_snapshot",
    "chunk_fingerprint",
    "is_chunk_complete",
    "read_catalog_delegations",
    "_fingerprint_matches",
    "_read_delegations",
    "_stamp_fingerprint",
    "_valid_partial_checkpoint",
    "_write_catalog_delegations",
]
