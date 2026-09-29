"""Publish a run's chunks as an immutable snapshot and move ``current``.

Publication is two steps and they are deliberately separate:

1. Merge the validated chunk Parquet files into one sorted artifact. This is
   out-of-core (``ORDER BY`` in DuckDB) so a run larger than memory still merges.
2. Write the pointer naming that snapshot as current.

The pointer is written *after* the artifact, never before. A pointer naming a
snapshot that does not exist is worse than a stale pointer, because a reader
following it finds a missing dataset instead of an older one.

A snapshot is immutable once published. Correcting a bad run means publishing a
new snapshot, which is what makes a published identity safe to record in
provenance elsewhere.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from edgar_sec.foundation.hashing import file_sha256, sha256_text
from edgar_sec.foundation.runtime.paths import current_pointer_path
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.document_parquet import (
    assemble_document_snapshots,
    validate_chunk_snapshot,
)
from edgar_sec.infra.storage.manifests import PART_KIND_INDEX, PART_KIND_PAYLOAD
from edgar_sec.infra.storage.parquet import read_parquet_table

log = logging.getLogger("document_storage.merger")

SNAPSHOT_ARTIFACT_NAME = "documents.parquet"
SNAPSHOT_MANIFEST_NAME = "manifest.json"
SNAPSHOT_SCHEMA_VERSION = "1"
PHASE = "025_webpage_storage"


class MergeError(RuntimeError):
    """A run could not be published as a snapshot."""


@dataclass(frozen=True, slots=True)
class SnapshotRef:
    """Identity of one published snapshot."""

    snapshot_id: str
    artifact_path: Path
    row_count: int
    chunk_count: int
    failed_documents: int
    missing_documents: int


@dataclass(frozen=True, slots=True)
class MergeResult:
    """Outcome of publishing one run."""

    run_id: str
    snapshot: SnapshotRef
    reused: bool
    warnings: tuple[str, ...] = field(default_factory=tuple)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def validate_chunks(chunk_paths: list[Path]) -> tuple[list[Path], list[str]]:
    """Split chunk paths into usable ones and warnings.

    A chunk that fails validation is *dropped with a warning* rather than
    failing the merge. Losing one chunk is recoverable and visible; refusing to
    publish because of it would also block the chunks that are fine.
    """
    usable: list[Path] = []
    warnings: list[str] = []
    for path in chunk_paths:
        if not path.is_file():
            warnings.append(f"chunk missing: {path.name}")
            continue
        try:
            validate_chunk_snapshot(path)
        except (ValueError, FileNotFoundError, OSError) as exc:
            warnings.append(f"chunk invalid: {path.name}: {exc}")
            continue
        usable.append(path)
    return usable, warnings


def _write_parts(staging: Path, artifact_path: Path) -> list[dict[str, Any]]:
    """Project an assembled snapshot into an index part and a payload part.

    A run publishes one combined table, but consolidation reads a part tree split
    by kind: index (metadata) and payload (text). Splitting here means every
    published snapshot is immediately consolidatable, rather than only the ones a
    previous consolidation happened to produce.
    """
    from edgar_sec.infra.storage.document_parts import (
        PlannedPart,
        write_index_part,
        write_payload_part,
    )
    from edgar_sec.infra.storage.parquet import read_parquet_table

    table = read_parquet_table(
        artifact_path,
        [
            "occurrence_id",
            "source_cik",
            "accession",
            "document_path",
            "blob_hash",
            "form",
            "filing_date",
            "byte_size",
            "normalized_text",
        ],
    )
    columns = {name: table.column(name).to_pylist() for name in table.schema.names}

    index_rows: list[dict[str, Any]] = []
    payloads: list[tuple[str, str]] = []
    for index in range(table.num_rows):
        doc_id = str(columns["blob_hash"][index] or "")
        payloads.append((doc_id, str(columns["normalized_text"][index] or "")))
        index_rows.append(
            {
                "occurrence_id": str(columns["occurrence_id"][index] or ""),
                "source_cik": str(columns["source_cik"][index] or ""),
                "accession": str(columns["accession"][index] or ""),
                "form": str(columns["form"][index] or ""),
                "filing_date": str(columns["filing_date"][index] or ""),
                "report_date": None,
                "document_path": str(columns["document_path"][index] or ""),
                "doc_id": doc_id,
                "mime_type": "text/plain",
                "byte_size": str(columns["byte_size"][index] or 0),
                "payload_file": "",
            }
        )

    index_rows.sort(key=lambda row: row["doc_id"])
    payloads.sort(key=lambda row: row[0])
    doc_ids = tuple(row["doc_id"] for row in index_rows)
    index_part = PlannedPart(
        path=f"parts/{PART_KIND_INDEX}/run.parquet",
        kind=PART_KIND_INDEX,
        doc_ids=doc_ids,
        estimated_bytes=sum(int(row["byte_size"]) for row in index_rows),
    )
    payload_part = PlannedPart(
        path=f"parts/{PART_KIND_PAYLOAD}/run.parquet",
        kind=PART_KIND_PAYLOAD,
        doc_ids=doc_ids,
        estimated_bytes=sum(int(row["byte_size"]) for row in index_rows),
    )
    parts = [
        write_index_part(staging, index_part, index_rows).to_dict(),
        write_payload_part(staging, payload_part, payloads).to_dict(),
    ]
    for row in index_rows:
        row["payload_file"] = payload_part.path
    # Rewrite the index now that each row knows which payload part holds its text.
    parts[0] = write_index_part(staging, index_part, index_rows).to_dict()
    return parts


def _failure_counts(artifact_path: Path) -> tuple[int, int]:
    """Return ``(failed, missing)`` document counts in a published artifact."""
    table = read_parquet_table(artifact_path, ["status"])
    statuses = table.column("status").to_pylist()
    failed = sum(1 for value in statuses if value == "failed")
    missing = sum(1 for value in statuses if value == "missing")
    return failed, missing


def content_fingerprint(chunk_paths: Sequence[Path]) -> str:
    """Return a stable content identity for a snapshot built from these chunks.

    Derived from the chunks' own digests rather than from the merged Parquet file.
    A Parquet file is not byte-stable across writes — the writer embeds metadata
    that varies — so a file digest would report two merges of identical content as
    different snapshots, and would make a consolidation's derived id unstable.

    Chunk checkpoints are themselves immutable and content-addressed, so hashing
    them identifies what the snapshot contains.
    """
    return sha256_text(
        canonical_json(
            {
                path.name: file_sha256(path)
                for path in sorted(chunk_paths, key=lambda p: p.name)
            }
        )
    )


def _write_manifest(
    snapshot_dir: Path,
    *,
    snapshot_id: str,
    run_id: str,
    artifact_file_sha256: str,
    logical_fingerprint: str,
    row_count: int,
    chunk_names: list[str],
    failed: int,
    missing: int,
    warnings: list[str],
    parts: list[dict[str, Any]],
) -> Path:
    manifest = {
        "snapshot_id": snapshot_id,
        "dataset": "document_storage",
        "phase": PHASE,
        "run_id": run_id,
        "published_at": _now(),
        "artifact_name": SNAPSHOT_ARTIFACT_NAME,
        # A file digest, not a content identity: see ``content_fingerprint``.
        "artifact_file_sha256": artifact_file_sha256,
        "row_count": row_count,
        "chunks": sorted(chunk_names),
        "failed_documents": failed,
        "missing_documents": missing,
        "warnings": warnings,
        # The part tree is what consolidation reads. The assembled artifact above
        # stays as the convenient single-file view; the parts are the canonical
        # decomposition a consumer can stream a quarter from.
        "resolved_parts": parts,
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "source_snapshot_ids": [run_id],
        "logical_fingerprint": logical_fingerprint,
    }
    path = snapshot_dir / SNAPSHOT_MANIFEST_NAME
    path.write_text(canonical_json(manifest), encoding="utf-8")
    return path


def _publish_pointer(snapshots_root: Path, snapshot_id: str, run_id: str) -> Path:
    """Point ``current`` at a snapshot that already exists on disk."""
    snapshots_root.mkdir(parents=True, exist_ok=True)
    pointer = current_pointer_path(snapshots_root)
    pointer.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "dataset": "document_storage",
        "snapshot_id": snapshot_id,
        "run_id": run_id,
        "pointed_at": _now(),
    }
    _atomic_write(pointer, canonical_json(payload))
    return pointer


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def publish_snapshot(
    *,
    run_id: str,
    chunks_dir: Path,
    snapshots_root: Path,
    snapshot_id: str | None = None,
) -> MergeResult:
    """Merge a run's chunks into an immutable snapshot and publish it.

    Args:
        run_id: identity of the run being published.
        chunks_dir: directory holding the run's chunk Parquet files.
        snapshots_root: root under which snapshots are stored.
        snapshot_id: explicit snapshot identity; derived from the run when absent.
    """
    chunk_paths = sorted(chunks_dir.glob("chunk-*.parquet"))
    if not chunk_paths:
        raise MergeError(f"no chunk checkpoints found in {chunks_dir}")

    usable, warnings = validate_chunks(chunk_paths)
    if not usable:
        raise MergeError(
            f"no usable chunk checkpoints in {chunks_dir}: {'; '.join(warnings)}"
        )

    resolved_snapshot_id = snapshot_id or f"snap-{sha256_text(run_id)[:12]}"
    snapshot_dir = snapshots_root / resolved_snapshot_id
    if snapshot_dir.exists():
        # Snapshots are immutable; republishing under the same id would rewrite
        # an identity other records already reference.
        raise MergeError(
            f"snapshot {resolved_snapshot_id} already exists at {snapshot_dir}"
        )

    snapshots_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(dir=str(snapshots_root), prefix=".staging-"))
    try:
        artifact = staging / SNAPSHOT_ARTIFACT_NAME
        row_count = assemble_document_snapshots(usable, artifact)
        failed, missing = _failure_counts(artifact)
        artifact_sha256 = file_sha256(artifact)
        parts = _write_parts(staging, artifact)
        _write_manifest(
            staging,
            snapshot_id=resolved_snapshot_id,
            run_id=run_id,
            artifact_file_sha256=artifact_sha256,
            logical_fingerprint=content_fingerprint(usable),
            row_count=row_count,
            chunk_names=[path.name for path in usable],
            failed=failed,
            missing=missing,
            warnings=warnings,
            parts=parts,
        )
        snapshot_dir.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, snapshot_dir)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    _publish_pointer(snapshots_root, resolved_snapshot_id, run_id)
    return MergeResult(
        run_id=run_id,
        snapshot=SnapshotRef(
            snapshot_id=resolved_snapshot_id,
            artifact_path=snapshot_dir / SNAPSHOT_ARTIFACT_NAME,
            row_count=row_count,
            chunk_count=len(usable),
            failed_documents=failed,
            missing_documents=missing,
        ),
        reused=False,
        warnings=tuple(warnings),
    )


def read_pointer(snapshots_root: Path) -> dict[str, Any] | None:
    """Read the pointer naming the currently published snapshot."""
    pointer = current_pointer_path(snapshots_root)
    if not pointer.is_file():
        return None
    return json.loads(pointer.read_text(encoding="utf-8"))


def current_snapshot_dir(snapshots_root: Path) -> Path | None:
    """Return the currently published snapshot's directory, if any."""
    pointer = read_pointer(snapshots_root)
    if pointer is None:
        return None
    snapshot_id = pointer.get("snapshot_id")
    if not snapshot_id:
        return None
    target = Path(snapshots_root) / str(snapshot_id)
    return target if target.is_dir() else None


def current_snapshot_artifact(snapshots_root: Path) -> Path | None:
    """Return the current snapshot's assembled artifact, or None.

    Only a *run* snapshot has an assembled ``documents.parquet``. A consolidated
    snapshot is a repartitioned part tree instead, so this returns None for it —
    which is why readers must not treat "no artifact" as "nothing published".
    Use :func:`current_snapshot_dir` to distinguish the two.
    """
    target = current_snapshot_dir(snapshots_root)
    if target is None:
        return None
    artifact = target / SNAPSHOT_ARTIFACT_NAME
    return artifact if artifact.is_file() else None


__all__ = [
    "SNAPSHOT_ARTIFACT_NAME",
    "SNAPSHOT_MANIFEST_NAME",
    "MergeError",
    "MergeResult",
    "SnapshotRef",
    "content_fingerprint",
    "current_snapshot_artifact",
    "current_snapshot_dir",
    "publish_snapshot",
    "read_pointer",
    "validate_chunks",
]
