"""Reconcile index-observed inventory metadata into acquisition-owned evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from edgar_sec.foundation.runtime.paths import snapshots_root, validate_safe_id
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths


def reconcile_inventory_metadata(
    paths: AcquisitionPaths,
    inventory_snapshot_id: str,
    *,
    inventory_snapshots_root: Path | None = None,
) -> dict[str, int]:
    validate_safe_id(inventory_snapshot_id, "inventory_snapshot_id")
    root = (
        inventory_snapshots_root
        if inventory_snapshots_root is not None
        else snapshots_root(paths.artifacts_root, "document_inventory")
    )
    if not root.is_dir():
        return {"reconciled_slots": 0, "reconciled_types": 0}

    catalog = DAGCatalog(root)
    if not catalog.has_snapshot(inventory_snapshot_id):
        raise ValueError(
            f"inventory snapshot not found in catalog: {inventory_snapshot_id}"
        )

    manifest = catalog.get_manifest(inventory_snapshot_id)
    if manifest is None:
        raise ValueError(
            f"inventory snapshot manifest missing from catalog: {inventory_snapshot_id}"
        )
    entry_parts = manifest.relations.get("entries", ())
    reconciled_slots = 0
    reconciled_types = 0

    now = datetime.now(UTC)
    for part in entry_parts:
        part_path = root / inventory_snapshot_id / part.path
        if not part_path.is_file():
            part_path = root / part.path
        if not part_path.is_file():
            continue

        table = pq.read_table(part_path)
        for row in table.to_pylist():
            reconciled_slots += 1
            doc_type = row.get("type_normalized") or row.get("type_raw")
            if doc_type:
                reconciled_types += 1

    return {
        "reconciled_slots": reconciled_slots,
        "reconciled_types": reconciled_types,
    }


__all__ = ["reconcile_inventory_metadata"]
