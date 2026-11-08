"""DAG publication of the company-facts store.

The snapshot carries the store's relations as Parquet parts written by
DuckDB COPY; its manifest metadata records the archive SHA lineage.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime

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

from .companyfacts import COMPANYFACTS_BULK_SOURCE_ID
from .facts_store import ARCHIVES_RELATION, FACTS_RELATION, MEMBERS_RELATION
from .paths import MetadataPaths

__all__ = ["FactsPublishOutcome", "facts_tip", "publish_facts"]

PUBLISH_RELATIONS = (FACTS_RELATION, MEMBERS_RELATION, ARCHIVES_RELATION)
SCHEMA_VERSION = "1"


@dataclass(frozen=True, slots=True)
class FactsPublishOutcome:
    """The publication outcome for one facts snapshot."""

    published: bool
    snapshot_id: str | None
    tip_before: str | None


def facts_tip(paths: MetadataPaths, branch: str = "main") -> str | None:
    """The current facts snapshot id on a branch, or None."""
    if not paths.facts_catalog_file.is_file():
        return None
    pointer = read_pointer(paths.facts_snapshots_root, branch)
    return str(pointer["snapshot_id"]) if pointer else None


def publish_facts(
    paths: MetadataPaths, *, branch: str = "main", now: datetime | None = None
) -> FactsPublishOutcome:
    """Publish the facts store's relations as the next DAG snapshot."""
    tip = facts_tip(paths, branch)
    if not paths.facts_store_file.is_file():
        return FactsPublishOutcome(published=False, snapshot_id=None, tip_before=tip)
    fetched_at = now or datetime.now(UTC)
    con = connect(database=paths.facts_store_file)
    try:
        existing = {
            str(row[0])
            for row in con.execute(
                "SELECT table_name FROM information_schema.tables"
            ).fetchall()
        }
        if ARCHIVES_RELATION not in existing:
            return FactsPublishOutcome(
                published=False, snapshot_id=None, tip_before=tip
            )
        archive_rows = con.execute(
            f"SELECT archive_sha, loaded_at FROM {sql_identifier(ARCHIVES_RELATION)} "
            "ORDER BY loaded_at DESC, archive_sha DESC LIMIT 1"
        ).fetchall()
        if not archive_rows:
            return FactsPublishOutcome(
                published=False, snapshot_id=None, tip_before=tip
            )
        archive_sha = str(archive_rows[0][0])
        member_rows = con.execute(
            f"SELECT cik, fingerprint FROM {sql_identifier(MEMBERS_RELATION)} "
            "ORDER BY cik"
        ).fetchall()
        fact_rows = int(
            con.execute(
                f"SELECT count(*) FROM {sql_identifier(FACTS_RELATION)}"
            ).fetchone()[0]
        )
    finally:
        con.close()
    relations = [name for name in PUBLISH_RELATIONS if name in existing]
    snapshot_id = _snapshot_id(archive_sha, member_rows, fact_rows)
    if snapshot_id == tip:
        return FactsPublishOutcome(published=False, snapshot_id=None, tip_before=tip)
    staging = paths.facts_transient_dir(snapshot_id) / "snapshot"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    descriptors: dict[str, PartDescriptor] = {}
    writer = connect()
    try:
        writer.execute(
            f"ATTACH {sql_literal(str(paths.facts_store_file))} AS store (READ_ONLY)"
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
    manifest = _manifest(paths, snapshot_id, tip, descriptors, fetched_at, archive_sha)
    publish_node(
        paths.facts_snapshots_root,
        manifest,
        staged_dir=staging,
        expected_parent_id=tip,
        branch_name=branch,
    )
    return FactsPublishOutcome(published=True, snapshot_id=snapshot_id, tip_before=tip)


def _snapshot_id(archive_sha: str, member_rows, fact_rows: int) -> str:
    """Content identity for a facts publish: archive lineage plus membership."""
    fingerprint = sha256_text(
        canonical_json(
            {
                "archive_sha": archive_sha,
                "members": [list(row) for row in member_rows],
                "fact_rows": fact_rows,
            }
        )
    )
    return f"companyfacts-{fingerprint[:24]}"


def _manifest(
    paths: MetadataPaths,
    snapshot_id: str,
    tip: str | None,
    descriptors: dict[str, PartDescriptor],
    fetched_at: datetime,
    archive_sha: str,
) -> DAGNodeManifest:
    parents: tuple[ParentRef, ...] = ()
    anchor = snapshot_id
    depth = 0
    if tip is not None:
        catalog = DAGCatalog(paths.facts_snapshots_root, read_only=True)
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
        metadata={
            "command": "facts-ingest",
            "source_id": COMPANYFACTS_BULK_SOURCE_ID,
            "archive_sha256": archive_sha,
            "fetched_at": fetched_at.isoformat(),
        },
    )
