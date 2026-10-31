"""Query and inspection interface for published acquisition snapshots."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa

from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.resolution import compile_virtual_views
from edgar_sec.infra.storage.dag.traversal import walk_lineage
from edgar_sec.infra.storage.duckdb import connect, sql_identifier
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths

from .schema import SNAPSHOT_RELATION_SCHEMAS
from .specs import ACQUISITION_RELATIONS, ACQUISITION_RELATIONS_BY_NAME


def get_snapshot_status(
    paths: AcquisitionPaths, branch_name: str = "main"
) -> dict[str, Any]:
    catalog = DAGCatalog(paths.snapshots_root)
    pointer = catalog.read_pointer(branch_name)
    if pointer is None:
        return {
            "branch": branch_name,
            "published": False,
            "snapshot_id": None,
            "message": "No snapshot published on branch",
        }
    snapshot_id = str(pointer["snapshot_id"])
    manifest = catalog.get_manifest(snapshot_id)
    if manifest is None:
        return {
            "branch": branch_name,
            "published": False,
            "snapshot_id": None,
            "message": "Snapshot manifest missing from catalog",
        }
    counts = {
        name: sum(part.row_count for part in parts)
        for name, parts in manifest.relations.items()
    }
    return {
        "branch": branch_name,
        "published": True,
        "snapshot_id": snapshot_id,
        "created_at": manifest.created_at,
        "kind": manifest.kind,
        "lineage_depth": manifest.lineage_depth,
        "parent_snapshot_id": manifest.parent_snapshot_id or None,
        "relation_counts": counts,
    }


def query_snapshot_relation(
    paths: AcquisitionPaths,
    relation_name: str,
    *,
    snapshot_id: str | None = None,
    branch_name: str = "main",
    columns: list[str] | None = None,
    limit: int | None = None,
) -> pa.Table:
    if relation_name not in ACQUISITION_RELATIONS_BY_NAME:
        raise ValueError(f"unknown relation name: {relation_name}")

    spec = ACQUISITION_RELATIONS_BY_NAME[relation_name]
    catalog = DAGCatalog(paths.snapshots_root)
    target_id = snapshot_id
    if target_id is None:
        pointer = catalog.read_pointer(branch_name)
        target_id = str(pointer["snapshot_id"]) if pointer else None

    if target_id is None:
        return pa.Table.from_batches([], schema=spec.schema)

    lineage = walk_lineage(paths.snapshots_root, target_id)

    con = connect()
    try:
        views = compile_virtual_views(
            con,
            ACQUISITION_RELATIONS,
            lineage,
            paths.snapshots_root,
        )
        active_view = views[relation_name]
        selected_cols = (
            ", ".join(sql_identifier(col) for col in columns) if columns else "*"
        )
        query = f"SELECT {selected_cols} FROM {active_view}"
        if limit is not None and limit > 0:
            query += f" LIMIT {limit}"
        return con.execute(query).to_arrow_table()
    finally:
        con.close()


def list_snapshots(paths: AcquisitionPaths) -> list[dict[str, Any]]:
    catalog = DAGCatalog(paths.snapshots_root)
    results = []
    for snap in catalog.list_snapshots():
        results.append(
            {
                "snapshot_id": snap["snapshot_id"],
                "kind": snap["kind"],
                "created_at": snap["created_at"],
                "lineage_depth": snap["lineage_depth"],
                "parent_snapshot_id": snap.get("parent_id") or None,
            }
        )
    return results


__all__ = [
    "get_snapshot_status",
    "list_snapshots",
    "query_snapshot_relation",
]
