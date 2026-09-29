"""Materialize an immutable filing-catalog snapshot from a Phase 1 snapshot.

Zero network: this module reads one published Parquet dataset and writes one
immutable catalog snapshot. It never constructs an HTTP client.

Three guards are load-bearing and are ported from the v1 contract:

1. a source path under ``chunks``, ``checkpoints``, or ``workers`` is refused,
   so a transient Phase 1 work unit can never be mistaken for a finalized
   snapshot;
2. the source column list must equal ``SUBMISSION_METADATA_SCHEMA.names``
   exactly, so a Phase 1 schema change fails loudly instead of producing a
   silently truncated catalog;
3. an existing snapshot directory is refused rather than overwritten, so a
   published snapshot stays immutable.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from edgar_sec.domain.filing_catalog.schemas import (
    PROFILE_SCHEMA_VERSION,
    SCHEMA_VERSION,
    TARGET_SCHEMA,
    TARGET_SCHEMA_VERSION,
)
from edgar_sec.domain.submissions.schemas import (
    SCHEMA_VERSION as SOURCE_SCHEMA_VERSION,
)
from edgar_sec.domain.submissions.schemas import SUBMISSION_METADATA_SCHEMA
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.runtime.memory import reclaim
from edgar_sec.foundation.runtime.progress import ProgressCallback, emit_progress
from edgar_sec.foundation.runtime.settings import resolve_settings
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.infra.storage.duckdb import connect
from edgar_sec.infra.storage.duckdb_catalog import (
    build_part_unnest_query,
    build_profile_query,
    copy_query_to_parquet,
    sql_literal,
)
from edgar_sec.infra.storage.parquet import (
    DEFAULT_ROW_GROUP_SIZE,
    read_parquet_schema,
)
from edgar_sec.pipelines.filing_catalog.paths import (
    PIPELINE_DIR,
    SNAPSHOT_FILE_NAME,
    SNAPSHOT_MANIFEST_NAME,
    TARGETS_DIR_NAME,
    resolve_filing_catalog_paths,
    target_part_name,
)
from edgar_sec.pipelines.metadata_sync.paths import resolve_metadata_paths

# Version of the archive-URL fallback policy baked into catalog_id derivation.
# Bump when the fallback rule changes, so the derived id changes with it.
FALLBACK_POLICY_VERSION = "1.1.0"

# Path components that identify transient Phase 1 state rather than a finalized
# snapshot. Present in these means the source is a work unit, not an artifact.
TRANSIENT_SOURCE_PARTS = frozenset({"chunks", "checkpoints", "workers"})


class CatalogError(RuntimeError):
    """A catalog invariant was violated and materialization cannot proceed."""


def _catalog_id(source_hash: str) -> str:
    """Derive a content-addressed catalog id from the source dataset."""
    payload = json.dumps(
        [source_hash, SOURCE_SCHEMA_VERSION, SCHEMA_VERSION, FALLBACK_POLICY_VERSION],
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _verify_source_digest(candidate: Path, expected: str, origin: Path) -> None:
    """Refuse a source whose bytes do not match the digest Phase 1 published.

    Phase 1 hashes the artifact it wrote, so a mismatch means the file was
    replaced or truncated after publication. Both call sites hash whole Parquet
    files, so this streams rather than reading them into memory.
    """
    if not expected:
        raise CatalogError(f"Phase 1 manifest records no artifact digest: {origin}")
    actual = file_sha256(candidate)
    if actual != expected:
        raise CatalogError(
            f"source artifact digest mismatch for {candidate}: "
            f"manifest {expected}, file {actual}"
        )


def resolve_source(
    source_artifact: str | os.PathLike[str] | None,
    source_manifest: str | os.PathLike[str] | None = None,
) -> tuple[Path, dict[str, Any] | None]:
    """Resolve the Phase 1 dataset this catalog consumes.

    With neither argument the currently published Phase 1 snapshot is used. An
    explicit manifest is read for its handoff metadata and the payload it names
    is what gets read as Parquet; a bare Parquet path is used directly.

    A manifest is metadata, not data. Returning the manifest path itself as the
    source would hand the JSON to the Parquet reader, so the payload is resolved
    from the manifest's ``output_path`` and checked against the
    ``artifact_sha256`` Phase 1 recorded with it.
    """
    handoff: dict[str, Any] | None = None
    candidate: Path | None = None
    expected_digest = ""

    if source_manifest is not None:
        manifest_path = Path(source_manifest).resolve()
        if not manifest_path.is_file():
            raise CatalogError(f"source manifest does not exist: {manifest_path}")
        handoff = json.loads(manifest_path.read_text(encoding="utf-8"))
        output_path = str(handoff.get("output_path") or "")
        if not output_path:
            raise CatalogError(
                f"Phase 1 manifest names no output_path: {manifest_path}"
            )
        candidate = Path(output_path)
        if not candidate.is_absolute():
            candidate = (manifest_path.parent / candidate).resolve()
        expected_digest = str(handoff.get("artifact_sha256") or "")
    elif source_artifact is not None:
        candidate = Path(source_artifact).resolve()

    if candidate is None:
        metadata_paths = resolve_metadata_paths()
        pointer = metadata_paths.current_pointer
        if not pointer.is_file():
            raise CatalogError(
                "no Phase 1 snapshot is published; run 'metadata merge' first or "
                "pass source_artifact explicitly"
            )
        handoff = json.loads(pointer.read_text(encoding="utf-8"))
        snapshot_id = handoff.get("snapshot_id")
        if not snapshot_id:
            raise CatalogError(f"Phase 1 pointer names no snapshot: {pointer}")
        candidate = metadata_paths.snapshot_file(str(snapshot_id))
        # The pointer is a discovery record rather than a manifest, so a pointer
        # written without a digest is usable; one that carries a digest is held
        # to it.
        expected_digest = str(handoff.get("artifact_sha256") or "")

    if not candidate.is_file():
        raise CatalogError(f"source artifact does not exist: {candidate}")
    if source_manifest is not None or expected_digest:
        _verify_source_digest(
            candidate,
            expected_digest,
            Path(source_manifest) if source_manifest is not None else candidate,
        )
    return candidate, handoff


def _guard_not_transient(source: Path) -> None:
    """Guard 1: refuse a transient Phase 1 work unit as a catalog source."""
    if any(part in TRANSIENT_SOURCE_PARTS for part in source.parts):
        raise CatalogError(
            f"Phase 2 requires a finalized artifact, not a chunk/checkpoint: {source}"
        )


def _guard_schema_matches(source: Path) -> None:
    """Guard 2: the source must be exactly the declared Phase 1 dataset."""
    actual = read_parquet_schema(source).names
    expected = SUBMISSION_METADATA_SCHEMA.names
    if list(actual) != list(expected):
        missing = [name for name in expected if name not in actual]
        extra = [name for name in actual if name not in expected]
        raise CatalogError(
            "source artifact columns do not match submission_metadata schema; "
            f"missing={missing} unexpected={extra}"
        )


def materialize(
    source_artifact: str | os.PathLike[str] | None = None,
    output_root: str | os.PathLike[str] | None = None,
    *,
    source_manifest: str | os.PathLike[str] | None = None,
    progress: ProgressCallback = None,
    source_batch_size: int | None = None,
    row_group_size: int | None = None,
) -> dict[str, Any]:
    """Materialize one immutable filing-catalog snapshot.

    Without ``output_root`` the snapshot is staged under the transient tree and
    published atomically into the durable snapshots tree, advancing the current
    pointer. An explicit ``output_root`` (tests, external tooling) writes the
    snapshot directory in place and never touches the pointer.

    Resource limits are intentionally *not* parameters here. ``connect()``
    derives threads, memory limit, and spill directory from the cgroup-aware
    ``derive_resources()``; re-exposing them as arguments invites the hardcoded
    allocations the ``resource-allocation`` scanner exists to block.
    """
    settings = resolve_settings()
    batch_size = int(
        source_batch_size
        if source_batch_size is not None
        else settings.get("catalog.source_batch_size", 1000)
    )
    if batch_size < 1:
        raise ValueError("source_batch_size must be >= 1")
    groups = int(
        row_group_size
        if row_group_size is not None
        else settings.get("catalog.row_group_size", DEFAULT_ROW_GROUP_SIZE)
    )

    source, handoff = resolve_source(source_artifact, source_manifest)
    _guard_not_transient(source)
    _guard_schema_matches(source)
    emit_progress(
        progress,
        {"type": "merge_stage", "stage": "validate_source", "source": str(source)},
    )

    paths = resolve_filing_catalog_paths(output_root)
    source_hash = file_sha256(source)
    snapshot_id = str((handoff or {}).get("snapshot_id") or _catalog_id(source_hash))
    catalog_id = snapshot_id

    # An explicit output_root is interpreted as an artifacts root, so the layout
    # agrees with resolve_filing_catalog_paths() and a catalog materialized into
    # a scratch directory can be planned from that same directory. It still
    # stages transiently and publishes atomically; only the pointer advance is
    # skipped.
    durable = output_root is None
    final_dir = paths.snapshot_dir(catalog_id)
    staging_dir = paths.transient_catalog_dir(catalog_id)

    # The immutability guard applies to both publication modes. v1 only enforced
    # it on the durable path, which meant an explicit --output-root could
    # silently destroy a previously published snapshot; the durable tree is the
    # contract, not the caller's choice of destination.
    if final_dir.exists():
        raise CatalogError(
            f"immutable catalog snapshot already exists: {final_dir}; prune it or "
            "advance to a new upstream snapshot"
        )

    if staging_dir.exists():
        shutil.rmtree(staging_dir, ignore_errors=True)
    staging_dir.mkdir(parents=True, exist_ok=True)

    with connect() as con:
        con.execute(
            f"CREATE OR REPLACE TEMP VIEW source AS "
            f"SELECT * FROM read_parquet({sql_literal(str(source))})"
        )

        profile_query = build_profile_query("source")
        profiles_path = staging_dir / SNAPSHOT_FILE_NAME
        profile_count = copy_query_to_parquet(con, profile_query, profiles_path, groups)
        emit_progress(
            progress,
            {
                "type": "merge_stage",
                "stage": "company_profiles",
                "rows": profile_count,
            },
        )

    reclaim()

    targets_dir = staging_dir / TARGETS_DIR_NAME
    if targets_dir.exists():
        shutil.rmtree(targets_dir)
    targets_dir.mkdir(parents=True, exist_ok=True)

    part_metadata: list[dict[str, Any]] = []
    form_counts: dict[str, int] = {}
    total_target_rows = 0
    with connect() as con:
        unnest = build_part_unnest_query(str(source))
        shard_name = target_part_name(0)
        shard_path = targets_dir / shard_name
        total_target_rows = copy_query_to_parquet(con, unnest, shard_path, groups)
        part_metadata.append(
            {
                "path": f"filing_targets/{shard_name}",
                "row_count": total_target_rows,
                "artifact_sha256": file_sha256(shard_path),
            }
        )
        for form_name, count in con.execute(
            f"SELECT form, COUNT(*) FROM read_parquet({sql_literal(str(shard_path))}) "
            f"WHERE form IS NOT NULL GROUP BY form ORDER BY form"
        ).fetchall():
            form_counts[str(form_name)] = int(count)

    reclaim()

    manifest = {
        "manifest_kind": "filing_catalog_snapshot",
        "catalog_id": catalog_id,
        "snapshot_id": snapshot_id,
        "source_artifact": str(source),
        "source_sha256": source_hash,
        "schema_version": SCHEMA_VERSION,
        "target_schema_version": TARGET_SCHEMA_VERSION,
        "profile_schema_version": PROFILE_SCHEMA_VERSION,
        "profile_row_count": profile_count,
        "target_row_count": total_target_rows,
        "target_columns": TARGET_SCHEMA.names,
        "form_counts": form_counts,
        "parts": part_metadata,
        "source_batch_size": batch_size,
        "pipeline": PIPELINE_DIR,
    }
    atomic_write_json(staging_dir / SNAPSHOT_MANIFEST_NAME, manifest, indent=2)

    # Always publish; only the pointer advance is reserved for the durable tree.
    final_dir.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging_dir, final_dir)
    if durable:
        atomic_write_json(
            paths.current_pointer,
            {
                "catalog_id": catalog_id,
                "snapshot_id": snapshot_id,
                "profile_row_count": profile_count,
                "target_row_count": total_target_rows,
                "schema_version": SCHEMA_VERSION,
            },
            indent=2,
        )
    emit_progress(
        progress,
        {
            "type": "merge_stage",
            "stage": "publish",
            "catalog_id": catalog_id,
            "rows": total_target_rows,
        },
    )
    return manifest


__all__ = [
    "FALLBACK_POLICY_VERSION",
    "TRANSIENT_SOURCE_PARTS",
    "CatalogError",
    "materialize",
    "resolve_source",
]
