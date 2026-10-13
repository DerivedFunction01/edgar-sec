"""Inspect one immutable inventory snapshot through its pinned DAG lineage."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pyarrow as pa

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.runtime.resources import RuntimeResourceProfile
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.query import compile_pruned_views
from edgar_sec.infra.storage.dag.traversal import walk_lineage
from edgar_sec.infra.storage.duckdb import connect, sql_identifier
from edgar_sec.pipelines.document_inventory.paths import InventoryPaths
from edgar_sec.pipelines.document_inventory.snapshot.specs import INVENTORY_RELATIONS


def inspect_snapshot(
    paths: InventoryPaths,
    snapshot: str = "current",
    *,
    branch: str = "main",
    profile: RuntimeResourceProfile | None = None,
) -> dict[str, Any]:
    catalog = DAGCatalog(paths.snapshots_root, read_only=True)
    if snapshot == "current":
        pointer = catalog.read_pointer(branch)
        if pointer is None:
            raise ValueError(f"inventory branch has no published snapshot: {branch}")
        snapshot_id = str(pointer["snapshot_id"])
    else:
        snapshot_id = snapshot
    node = catalog.get_manifest(snapshot_id)
    if node is None:
        raise ValueError(f"inventory snapshot is not published: {snapshot_id}")
    lineage = walk_lineage(paths.snapshots_root, snapshot_id, read_only=True)
    manifest_digest = catalog.get_manifest_sha256(snapshot_id)
    if manifest_digest is None:
        raise ValueError(f"inventory snapshot manifest is unavailable: {snapshot_id}")

    parts = []
    physical_counts = {}
    for spec in INVENTORY_RELATIONS:
        owned_parts = [
            (ancestor, part)
            for ancestor in lineage.nodes
            for part in ancestor.relations.get(spec.name, ())
        ]
        physical_counts[spec.name] = len(owned_parts)
        for owner, descriptor in owned_parts:
            relative = Path(descriptor.path)
            if relative.is_absolute():
                path = relative.resolve()
            else:
                candidate = paths.snapshots_root / owner.snapshot_id / relative
                path = candidate.resolve() if candidate.is_file() else None
                if path is None:
                    path = (paths.snapshots_root / relative).resolve()
            try:
                path.relative_to(paths.snapshots_root.resolve())
            except ValueError as error:
                raise ValueError("inventory part escapes the snapshot root") from error
            if not path.is_file() or file_sha256(path) != descriptor.sha256:
                raise ValueError(
                    f"inventory part is missing or corrupt: {descriptor.path}"
                )
            try:
                parquet = pq.ParquetFile(path)
            except (OSError, pa.ArrowException, pq.ParquetException) as error:
                raise ValueError(
                    f"inventory part is unreadable: {descriptor.path}"
                ) from error
            if (
                path.stat().st_size != descriptor.byte_size
                or parquet.metadata.num_rows != descriptor.row_count
                or parquet.schema_arrow != spec.schema
            ):
                raise ValueError(f"inventory part metadata mismatch: {descriptor.path}")
            parts.append(
                {
                    "relation": spec.name,
                    "path": descriptor.path,
                    "row_count": descriptor.row_count,
                    "byte_size": descriptor.byte_size,
                    "sha256": descriptor.sha256,
                    "key_min": descriptor.key_min,
                    "key_max": descriptor.key_max,
                }
            )

    con = connect(profile)
    try:
        compile_pruned_views(con, INVENTORY_RELATIONS, lineage, paths.snapshots_root)
        cursor = con.execute(
            "SELECT form, substr(filing_date, 1, 4) AS filing_year, count(*) AS accession_count "
            "FROM active_accessions GROUP BY form, filing_year ORDER BY form, filing_year"
        )
        counts_by_form_year = [
            {"form": form, "filing_year": year, "accession_count": count}
            for form, year, count in cursor.fetchall()
        ]
        row_counts = {
            spec.name: int(
                con.execute(
                    f"SELECT count(*) FROM {sql_identifier(f'active_{spec.name}')}"
                ).fetchone()[0]
            )
            for spec in INVENTORY_RELATIONS
        }
    finally:
        con.close()

    return {
        "snapshot_id": snapshot_id,
        "branch": branch if snapshot == "current" else None,
        "manifest_sha256": manifest_digest,
        "logical_fingerprint": node.logical_fingerprint,
        "lineage": [item.snapshot_id for item in lineage.nodes],
        "partition_layout": {
            "physical_partition_key": "relation",
            "annual_partitioning": False,
            "annual_counts_are_logical": True,
            "parts_by_relation": physical_counts,
        },
        "counts_by_form_filing_year": counts_by_form_year,
        "active_row_counts": row_counts,
        "parts": parts,
    }


__all__ = ["inspect_snapshot"]
