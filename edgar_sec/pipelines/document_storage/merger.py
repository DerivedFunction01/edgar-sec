"""Publish a run's chunks as an immutable snapshot and move ``current``.

The pointer is written after the artifact, never before: a pointer to a missing
snapshot is worse than a stale one. A published snapshot is never rewritten.
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
from pathlib import PurePosixPath
from typing import Any

from edgar_sec.foundation.hashing import file_sha256, sha256_text
from edgar_sec.foundation.runtime.paths import DOCUMENTS_DATASET, current_pointer_path
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.duckdb import connect, copy_query_to_parquet, sql_path_list
from edgar_sec.infra.storage.manifests import PART_KIND_INDEX, PART_KIND_PAYLOAD
from edgar_sec.infra.storage.parquet import (
    count_parquet_rows,
    read_parquet_schema,
    read_parquet_table,
)
from edgar_sec.pipelines.document_storage.checkpoint import (
    DOCUMENT_SNAPSHOT_SCHEMA,
    validate_chunk_snapshot,
)
from edgar_sec.pipelines.document_storage.paths import (
    DOCUMENTS_PHASE,
    SNAPSHOT_ARTIFACT_NAME,
)
from edgar_sec.pipelines.document_storage.queries import chunk_assembly_query

log = logging.getLogger("document_storage.merger")

SNAPSHOT_MANIFEST_NAME = "manifest.json"
SNAPSHOT_SCHEMA_VERSION = "2"


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

    A failing chunk is dropped, not fatal: refusing to publish would also block the
    chunks that are fine.
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

    Splitting here makes every published snapshot immediately consolidatable.
    """
    from edgar_sec.infra.storage.parquet import read_parquet_table
    from edgar_sec.pipelines.document_storage.parts import (
        PlannedPart,
        write_index_part,
        write_payload_part,
    )

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
            "report_date",
            "metadata",
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
                "report_date": columns["report_date"][index],
                "document_path": str(columns["document_path"][index] or ""),
                "doc_id": doc_id,
                "mime_type": "text/plain",
                "byte_size": str(columns["byte_size"][index] or 0),
                "payload_file": "",
                "metadata": columns["metadata"][index] or "{}",
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
    for part in parts:
        part["sha256"] = file_sha256(staging / part["path"])
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

    Derived from the chunks' digests, not the merged Parquet file: Parquet embeds
    metadata that varies between writes of identical content.
    """
    return sha256_text(
        canonical_json(
            {
                path.name: file_sha256(path)
                for path in sorted(chunk_paths, key=lambda p: p.name)
            }
        )
    )


def _conflict_check_query(chunk_paths: Sequence[str]) -> str:
    """Check for conflicting rows for the same occurrence_id across chunks.

    Conflicts are a data-integrity error: the merge collapses identical duplicates
    and refuses any differing identity, metadata, payload/text, or row metadata.
    """
    return f"""
        WITH assembled AS (
            SELECT * FROM read_parquet({sql_path_list([str(p) for p in chunk_paths])})
        ),
        grouped AS (
            SELECT
                occurrence_id,
                COUNT(*) AS n,
                COUNT(DISTINCT (
                    blob_hash, source_cik, accession, form, filing_date, report_date,
                    status, error_message,
                    COALESCE(metadata, '{{}}'),
                    sha256(COALESCE(normalized_text, '')),
                    sha256(raw_payload)
                )) AS distinct_values
            FROM assembled
            GROUP BY occurrence_id
            HAVING COUNT(*) > 1
        )
        SELECT occurrence_id FROM grouped WHERE distinct_values > 1
    """


def _deduped_assembly_query(chunk_paths: Sequence[str]) -> str:
    """Assemble the snapshot with identical rows collapsed to one per occurrence_id.

    Identical duplicates keep the first row by source_cik, accession, path;
    conflicting duplicates are rejected by the conflict check above.
    """
    from edgar_sec.pipelines.document_storage.checkpoint import (
        DOCUMENT_SNAPSHOT_SCHEMA,
    )

    return f"""
        WITH assembled AS (
            SELECT * FROM read_parquet({sql_path_list([str(p) for p in chunk_paths])})
        ),
        ranked AS (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY occurrence_id
                    ORDER BY source_cik, accession, document_path, blob_hash
                ) AS _rn
            FROM assembled
        )
        SELECT {", ".join(DOCUMENT_SNAPSHOT_SCHEMA.names)} FROM ranked WHERE _rn = 1
    """


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
        "dataset": DOCUMENTS_DATASET,
        "phase": DOCUMENTS_PHASE,
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
        # The part tree is what consolidation reads; the assembled artifact above
        # stays as the single-file view.
        "resolved_parts": parts,
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "source_snapshot_ids": [run_id],
        "logical_fingerprint": logical_fingerprint,
    }
    path = snapshot_dir / SNAPSHOT_MANIFEST_NAME
    _atomic_write(path, canonical_json(manifest))
    return path


def _publish_pointer(snapshots_root: Path, snapshot_id: str, run_id: str) -> Path:
    """Point ``current`` at a snapshot that already exists on disk."""
    snapshots_root.mkdir(parents=True, exist_ok=True)
    pointer = current_pointer_path(snapshots_root)
    pointer.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "dataset": DOCUMENTS_DATASET,
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
    reuse_existing: bool = False,
) -> MergeResult:
    """Merge a run's chunks into an immutable snapshot and publish it."""
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
        if reuse_existing:
            return _reuse_existing_snapshot(
                run_id=run_id,
                snapshot_id=resolved_snapshot_id,
                snapshot_dir=snapshot_dir,
                chunk_paths=chunk_paths,
                usable=usable,
                warnings=warnings,
            )
        raise MergeError(
            f"snapshot {resolved_snapshot_id} already exists at {snapshot_dir}"
        )

    snapshots_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(dir=str(snapshots_root), prefix=".staging-"))
    try:
        artifact = staging / SNAPSHOT_ARTIFACT_NAME
        with connect() as con:
            conflict_rows = list(
                con.execute(
                    _conflict_check_query([str(path) for path in usable])
                ).fetchall()
            )
            if conflict_rows:
                ids = ", ".join(str(r[0]) for r in conflict_rows[:50])
                raise MergeError(
                    f"conflicting rows for {len(conflict_rows)} occurrence_id(s) "
                    f"across chunks: {ids}"
                )
            row_count = copy_query_to_parquet(
                con,
                _deduped_assembly_query([str(path) for path in usable]),
                artifact,
            )
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


def _reuse_existing_snapshot(
    *,
    run_id: str,
    snapshot_id: str,
    snapshot_dir: Path,
    chunk_paths: Sequence[Path],
    usable: Sequence[Path],
    warnings: Sequence[str],
) -> MergeResult:
    from edgar_sec.pipelines.document_storage.parts import (
        INDEX_COLUMNS,
        PAYLOAD_COLUMNS,
    )

    manifest_path = snapshot_dir / SNAPSHOT_MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("snapshot manifest is not an object")
        expected_chunks = sorted(path.name for path in usable)
        if (
            manifest.get("snapshot_id") != snapshot_id
            or manifest.get("run_id") != run_id
            or manifest.get("dataset") != DOCUMENTS_DATASET
            or manifest.get("phase") != DOCUMENTS_PHASE
            or manifest.get("schema_version") != SNAPSHOT_SCHEMA_VERSION
            or manifest.get("artifact_name") != SNAPSHOT_ARTIFACT_NAME
            or manifest.get("chunks") != expected_chunks
            or manifest.get("logical_fingerprint") != content_fingerprint(usable)
            or list(manifest.get("warnings", ())) != list(warnings)
            or manifest.get("source_snapshot_ids") != [run_id]
            or len(usable) != len(chunk_paths)
        ):
            raise ValueError("snapshot manifest identity does not match this run")

        artifact = snapshot_dir / SNAPSHOT_ARTIFACT_NAME
        if not artifact.is_file():
            raise ValueError("snapshot artifact is missing")
        if file_sha256(artifact) != manifest.get("artifact_file_sha256"):
            raise ValueError("snapshot artifact digest does not match its manifest")
        if count_parquet_rows(artifact) != int(manifest.get("row_count", -1)):
            raise ValueError("snapshot artifact row count does not match its manifest")
        if read_parquet_schema(artifact).names != DOCUMENT_SNAPSHOT_SCHEMA.names:
            raise ValueError("snapshot artifact schema does not match the checkpoint")

        parts = manifest.get("resolved_parts")
        if not isinstance(parts, list) or not parts:
            raise ValueError("snapshot manifest records no parts")
        seen_paths: set[str] = set()
        kinds: set[str] = set()
        for part in parts:
            if not isinstance(part, dict):
                raise ValueError("snapshot part entry is invalid")
            relative = str(part.get("path") or "")
            relative_path = PurePosixPath(relative)
            if (
                not relative
                or relative_path.is_absolute()
                or ".." in relative_path.parts
                or "\\" in relative
                or relative in seen_paths
            ):
                raise ValueError("snapshot part path is unsafe or duplicated")
            seen_paths.add(relative)
            kind = str(part.get("kind") or "")
            kinds.add(kind)
            part_path = (snapshot_dir / relative).resolve()
            part_path.relative_to(snapshot_dir.resolve())
            if not part_path.is_file():
                raise ValueError(f"snapshot part is missing: {relative}")
            if part_path.stat().st_size != int(part.get("byte_size", -1)):
                raise ValueError(f"snapshot part size differs: {relative}")
            if file_sha256(part_path) != part.get("sha256"):
                raise ValueError(f"snapshot part digest differs: {relative}")
            if count_parquet_rows(part_path) != int(part.get("row_count", -1)):
                raise ValueError(f"snapshot part row count differs: {relative}")
            expected_schema = (
                INDEX_COLUMNS
                if kind == PART_KIND_INDEX
                else PAYLOAD_COLUMNS
                if kind == PART_KIND_PAYLOAD
                else ()
            )
            if not expected_schema or read_parquet_schema(part_path).names != list(
                expected_schema
            ):
                raise ValueError(f"snapshot part schema differs: {relative}")
        if kinds != {PART_KIND_INDEX, PART_KIND_PAYLOAD}:
            raise ValueError("snapshot manifest has an incomplete part-kind set")
        failed = int(manifest.get("failed_documents", -1))
        missing = int(manifest.get("missing_documents", -1))
        row_count = int(manifest["row_count"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise MergeError(
            f"existing snapshot {snapshot_id} is incomplete or conflicting: {exc}"
        ) from exc

    return MergeResult(
        run_id=run_id,
        snapshot=SnapshotRef(
            snapshot_id=snapshot_id,
            artifact_path=snapshot_dir / SNAPSHOT_ARTIFACT_NAME,
            row_count=row_count,
            chunk_count=len(usable),
            failed_documents=failed,
            missing_documents=missing,
        ),
        reused=True,
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

    None means the current snapshot may be a consolidated part tree, so it does not
    mean nothing is published; use :func:`current_snapshot_dir` to tell them apart.
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
