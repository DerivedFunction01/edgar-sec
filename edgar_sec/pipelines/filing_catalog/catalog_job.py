"""Materialize an immutable filing-catalog snapshot from a metadata snapshot.
Four guards are invariants: a transient source is refused, the column list must
exactly match the source schema, an existing snapshot is never overwritten, and
parts must be CIK-disjoint.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, NamedTuple

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
from edgar_sec.infra.storage.duckdb import (
    connect,
    copy_query_to_parquet,
    sql_literal,
    sql_path_list,
)
from edgar_sec.infra.storage.parquet import (
    DEFAULT_ROW_GROUP_SIZE,
    read_parquet_schema,
)
from edgar_sec.pipelines.filing_catalog.materialization import (
    build_part_unnest_query,
    build_profile_query,
)
from edgar_sec.pipelines.filing_catalog.paths import (
    PIPELINE_DIR,
    SNAPSHOT_FILE_NAME,
    SNAPSHOT_MANIFEST_NAME,
    TARGETS_DIR_NAME,
    resolve_filing_catalog_paths,
    target_part_name,
)
from edgar_sec.pipelines.metadata_sync.merger import parts_digest
from edgar_sec.pipelines.metadata_sync.paths import resolve_metadata_paths
from edgar_sec.pipelines.metadata_sync.snapshot import (
    SnapshotLayoutError,
    read_snapshot_parts,
)

FALLBACK_POLICY_VERSION = "1.1.0"

TRANSIENT_SOURCE_PARTS = frozenset({"chunks", "checkpoints", "workers"})
TARGET_SORT_ORDER = "source_part_order"


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
    """Refuse a source whose bytes do not match the digest the manifest published.

    A mismatch means the file was replaced or truncated after publication.
    """
    if not expected:
        raise CatalogError(f"Phase 1 manifest records no artifact digest: {origin}")
    actual = file_sha256(candidate)
    if actual != expected:
        raise CatalogError(
            f"source artifact digest mismatch for {candidate}: "
            f"manifest {expected}, file {actual}"
        )


class SourceDataset(NamedTuple):
    """A resolved Phase 1 source: the parts to read and their handoff metadata."""

    paths: tuple[Path, ...]
    handoff: dict[str, Any] | None

    @property
    def part_count(self) -> int:
        return len(self.paths)

    @property
    def first(self) -> Path:
        """The first part; used for messages and single-file display."""
        return self.paths[0]


def resolve_source(
    source_artifact: str | os.PathLike[str] | None,
    source_manifest: str | os.PathLike[str] | None = None,
) -> SourceDataset:
    """Resolve the source dataset this catalog consumes.
    Three entries converge on an ordered part list: a manifest, whose parts are
    digest-verified; a Parquet path; or the current pointer.
    """
    if source_manifest is not None:
        return _source_from_manifest(Path(source_manifest))
    if source_artifact is not None:
        candidate = Path(source_artifact).resolve()
        if not candidate.is_file():
            raise CatalogError(f"source artifact does not exist: {candidate}")
        return SourceDataset(paths=(candidate,), handoff=None)
    return _source_from_pointer()


def _source_from_manifest(manifest_path: Path) -> SourceDataset:
    if not manifest_path.is_file():
        raise CatalogError(f"source manifest does not exist: {manifest_path}")
    try:
        parts = read_snapshot_parts(manifest_path)
    except SnapshotLayoutError as exc:
        raise CatalogError(str(exc)) from exc
    return SourceDataset(paths=parts.paths, handoff=parts.layout.manifest)


def _source_from_pointer() -> SourceDataset:
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
    try:
        parts = read_snapshot_parts(metadata_paths.snapshot_manifest(str(snapshot_id)))
    except SnapshotLayoutError as exc:
        raise CatalogError(str(exc)) from exc
    return SourceDataset(paths=parts.paths, handoff=parts.layout.manifest)


def _guard_not_transient(source: SourceDataset) -> None:
    """Refuse a transient source work unit as a catalog source."""
    for path in source.paths:
        if any(part in TRANSIENT_SOURCE_PARTS for part in path.parts):
            raise CatalogError(
                f"Phase 2 requires a finalized artifact, not a chunk/checkpoint: {path}"
            )


def _guard_schema_matches(source: SourceDataset) -> None:
    """Every part must be exactly the declared source dataset."""
    expected = SUBMISSION_METADATA_SCHEMA.names
    for path in source.paths:
        actual = read_parquet_schema(path).names
        if list(actual) != list(expected):
            missing = [name for name in expected if name not in actual]
            extra = [name for name in actual if name not in expected]
            raise CatalogError(
                f"source artifact columns do not match submission_metadata schema; "
                f"missing={missing} unexpected={extra} ({path})"
            )


def _guard_ciks_are_disjoint(source: SourceDataset) -> None:
    """Each CIK must appear in exactly one source part.
    The target pass dedupes within a part only, so a CIK spanning two would publish
    the same ``occurrence_id`` twice. The check prunes to the ``cik`` column.
    """
    if source.part_count < 2:
        return
    listed = sql_path_list([str(path) for path in source.paths])
    with connect() as con:
        conflicts = con.execute(
            f"""
            SELECT cik, count(DISTINCT filename) AS parts
            FROM read_parquet({listed}, filename = true)
            WHERE cik IS NOT NULL
            GROUP BY cik
            HAVING count(DISTINCT filename) > 1
            ORDER BY cik
            LIMIT 5
            """
        ).fetchall()
    if conflicts:
        detail = ", ".join(f"{cik} in {parts} parts" for cik, parts in conflicts)
        raise CatalogError(
            "source parts share CIKs; a sharded catalog would publish duplicate "
            f"occurrence ids across shards ({detail})"
        )


def materialize(
    source_artifact: str | os.PathLike[str] | None = None,
    output_root: str | os.PathLike[str] | None = None,
    *,
    source_manifest: str | os.PathLike[str] | None = None,
    progress: ProgressCallback = None,
    row_group_size: int | None = None,
) -> dict[str, Any]:
    """Materialize one immutable filing-catalog snapshot.
    An explicit ``output_root`` publishes in place and never touches the pointer.
    Resource limits are not parameters: ``connect()`` derives them.
    """
    settings = resolve_settings()
    groups = int(
        row_group_size
        if row_group_size is not None
        else settings.get("catalog.row_group_size", DEFAULT_ROW_GROUP_SIZE)
    )

    source = resolve_source(source_artifact, source_manifest)
    _guard_not_transient(source)
    _guard_schema_matches(source)
    _guard_ciks_are_disjoint(source)
    emit_progress(
        progress,
        {
            "type": "merge_stage",
            "stage": "validate_source",
            "parts": source.part_count,
        },
    )

    paths = resolve_filing_catalog_paths(output_root)
    # A catalog id must identify the dataset, not one file of it: an
    # upstream id wins, else the ordered part digests do, so two layouts holding
    # the same rows resolve to the same catalog.
    source_hash = str((source.handoff or {}).get("parts_digest") or "") or parts_digest(
        [{"sha256": file_sha256(path)} for path in source.paths]
    )
    snapshot_id = str(
        (source.handoff or {}).get("snapshot_id") or _catalog_id(source_hash)
    )
    catalog_id = snapshot_id

    # An explicit output_root is read as an artifacts root, so a catalog written
    # to a scratch directory can be planned from that same directory.
    durable = output_root is None
    final_dir = paths.snapshot_dir(catalog_id)
    staging_dir = paths.transient_catalog_dir(catalog_id)

    # Immutability applies to both publication modes: an existing
    # destination snapshot is never overwritten.
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
            "CREATE OR REPLACE TEMP VIEW source AS SELECT * FROM "
            f"read_parquet({sql_path_list([str(path) for path in source.paths])})"
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
    # One source part per query and per shard. reclaim() between parts returns the
    # previous part's arena pages to the OS, so peak memory is set by the densest
    # single part rather than by a fragmented heap.
    with connect() as con:
        for index, source_path in enumerate(source.paths):
            shard_name = target_part_name(index)
            shard_path = targets_dir / shard_name
            rows = copy_query_to_parquet(
                con, build_part_unnest_query(str(source_path)), shard_path, groups
            )
            total_target_rows += rows
            part_metadata.append(
                {
                    "path": f"{TARGETS_DIR_NAME}/{shard_name}",
                    "part_index": index,
                    "source_part": str(source_path),
                    "row_count": rows,
                    "artifact_sha256": file_sha256(shard_path),
                }
            )
            for form_name, count in con.execute(
                f"SELECT form, COUNT(*) FROM read_parquet({sql_literal(str(shard_path))}) "
                f"WHERE form IS NOT NULL GROUP BY form ORDER BY form"
            ).fetchall():
                form_counts[str(form_name)] = form_counts.get(str(form_name), 0) + int(
                    count
                )
            emit_progress(
                progress,
                {
                    "type": "merge_stage",
                    "stage": f"filing_targets:{shard_name}",
                    "rows": rows,
                },
            )
            reclaim()

    reclaim()

    manifest = {
        "manifest_kind": "filing_catalog_snapshot",
        "catalog_id": catalog_id,
        "snapshot_id": snapshot_id,
        "source_artifact": str(source.first),
        "source_parts": [str(path) for path in source.paths],
        "source_part_count": source.part_count,
        "source_sha256": source_hash,
        "schema_version": SCHEMA_VERSION,
        "target_schema_version": TARGET_SCHEMA_VERSION,
        "profile_schema_version": PROFILE_SCHEMA_VERSION,
        "profile_row_count": profile_count,
        "target_row_count": total_target_rows,
        "target_columns": TARGET_SCHEMA.names,
        "form_counts": form_counts,
        "parts": part_metadata,
        "target_part_count": len(part_metadata),
        "sort_order": TARGET_SORT_ORDER,
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
    "TARGET_SORT_ORDER",
    "TRANSIENT_SOURCE_PARTS",
    "CatalogError",
    "materialize",
    "resolve_source",
]
