"""DAG publication of the datasets index snapshot.

The snapshot carries the store's index relations as Parquet parts; the
dataset tables stay in the DuckDB store the snapshot indexes. Parts are
written by DuckDB COPY, never from Python rows.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from edgar_sec.foundation.hashing import file_sha256, sha256_text
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.manifest import (
    DAGNodeManifest,
    ParentRef,
    PartDescriptor,
    ordered_parts_fingerprint,
)
from edgar_sec.infra.storage.dag.publication import publish_node, read_pointer
from edgar_sec.infra.storage.duckdb import connect, sql_identifier, sql_literal

from .paths import DatasetsPaths
from .store import POPULATION_RELATION, VINTAGES_RELATION, open_store

INDEX_RELATIONS = (VINTAGES_RELATION, "dataset_vintage_tables", POPULATION_RELATION)
SCHEMA_VERSION = "1"


@dataclass(frozen=True, slots=True)
class PublishOutcome:
    """The publication outcome for one index snapshot."""

    published: bool
    snapshot_id: str | None
    tip_before: str | None


def store_tip(paths: DatasetsPaths, branch: str = "main") -> str | None:
    """The current index snapshot id on a branch, or None."""
    if not paths.catalog_file.is_file():
        return None
    pointer = read_pointer(paths.snapshots_root, branch)
    return str(pointer["snapshot_id"]) if pointer else None


def publish_index(
    paths: DatasetsPaths, *, branch: str = "main", now: datetime | None = None
) -> PublishOutcome:
    """Publish the store's index relations as the next DAG snapshot."""
    tip = store_tip(paths, branch)
    fetched_at = now or datetime.now(UTC)
    con = open_store(paths.store_file)
    try:
        existing = {
            str(row[0])
            for row in con.execute(
                "SELECT table_name FROM information_schema.tables"
            ).fetchall()
        }
        relations = [name for name in INDEX_RELATIONS if name in existing]
        if VINTAGES_RELATION not in existing:
            return PublishOutcome(published=False, snapshot_id=None, tip_before=tip)
        fingerprint_rows = con.execute(
            f"SELECT set_id, vintage, archive_sha FROM {sql_identifier(VINTAGES_RELATION)} "
            "ORDER BY set_id, vintage, archive_sha"
        ).fetchall()
        population_rows = (
            int(
                con.execute(
                    f"SELECT count(*) FROM {sql_identifier(POPULATION_RELATION)}"
                ).fetchone()[0]
            )
            if POPULATION_RELATION in existing
            else 0
        )
    finally:
        con.close()
    snapshot_id = _snapshot_id(fingerprint_rows, population_rows)
    if snapshot_id == tip:
        return PublishOutcome(published=False, snapshot_id=None, tip_before=tip)
    staging = paths.transient_dir(snapshot_id) / "snapshot"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    descriptors: dict[str, PartDescriptor] = {}
    writer = connect()
    try:
        writer.execute(
            f"ATTACH {sql_literal(str(paths.store_file))} AS store (READ_ONLY)"
        )
        for relation in relations:
            part = staging / f"{relation}.parquet"
            writer.execute(
                f"COPY {sql_identifier('store.' + relation)} TO {sql_literal(str(part))} (FORMAT PARQUET)"
            )
            count = int(
                writer.execute(
                    f"SELECT count(*) FROM {sql_identifier('store.' + relation)}"
                ).fetchone()[0]
            )
            descriptors[relation] = PartDescriptor(
                path=f"{snapshot_id}/{relation}.parquet",
                sha256=file_sha256(part),
                row_count=count,
                byte_size=part.stat().st_size,
            )
    finally:
        writer.close()
    manifest = _manifest(paths, snapshot_id, tip, descriptors, fetched_at)
    publish_node(
        paths.snapshots_root,
        manifest,
        staged_dir=staging,
        expected_parent_id=tip,
        branch_name=branch,
    )
    return PublishOutcome(published=True, snapshot_id=snapshot_id, tip_before=tip)


def _snapshot_id(rows, population_rows: int) -> str:
    """Content identity for an index publish: the indexed slices themselves."""
    fingerprint = sha256_text(
        canonical_json(
            {
                "vintages": [list(row) for row in rows],
                "population_rows": population_rows,
            }
        )
    )
    return f"datasets-{fingerprint[:24]}"


def _manifest(
    paths: DatasetsPaths,
    snapshot_id: str,
    tip: str | None,
    descriptors: dict[str, PartDescriptor],
    fetched_at: datetime,
) -> DAGNodeManifest:
    parents: tuple[ParentRef, ...] = ()
    anchor = snapshot_id
    depth = 0
    if tip is not None:
        catalog = DAGCatalog(paths.snapshots_root, read_only=True)
        parent = catalog.get_manifest(tip)
        parents = (
            ParentRef(
                snapshot_id=tip,
                manifest_sha256=catalog.get_manifest_sha256(tip) or "",
            ),
        )
        if parent is not None:
            anchor = parent.checkpoint_anchor_id or tip
            depth = parent.lineage_depth + 1
    return DAGNodeManifest(
        snapshot_id=snapshot_id,
        kind="delta" if tip is not None else "checkpoint",
        parents=parents,
        checkpoint_anchor_id=anchor,
        lineage_depth=depth,
        created_at=fetched_at.isoformat(),
        relations={name: (desc,) for name, desc in sorted(descriptors.items())},
        logical_fingerprint=ordered_parts_fingerprint(
            [desc.sha256 for desc in descriptors.values()]
        ),
        schema_versions={name: SCHEMA_VERSION for name in descriptors},
        metadata={"command": "publish", "fetched_at": fetched_at.isoformat()},
    )


__all__ = ["PublishOutcome", "publish_index", "store_tip"]
