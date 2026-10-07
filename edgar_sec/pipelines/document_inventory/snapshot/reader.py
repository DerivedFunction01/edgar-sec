"""High-level query adapter for document inventory snapshots.

Executes range-pruned point lookups against active virtual views.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from edgar_sec.foundation.runtime.paths import (
    CURRENT_DIR,
    POINTER_FILE_NAME,
    SNAPSHOTS_DIR,
)
from edgar_sec.foundation.runtime.resources import RuntimeResourceProfile
from edgar_sec.infra.storage.dag.publication import read_pointer
from edgar_sec.infra.storage.dag.query import query_point
from edgar_sec.infra.storage.dag.traversal import walk_lineage
from edgar_sec.infra.storage.duckdb import connect
from edgar_sec.pipelines.document_inventory.paths import DATASET
from edgar_sec.pipelines.document_inventory.snapshot.specs import (
    INVENTORY_ACCESSIONS_SPEC,
    INVENTORY_ENTRIES_SPEC,
    INVENTORY_RELATIONS,
)


def _resolve_snapshots_root(root: Path | str) -> Path:
    """Resolve artifacts or snapshot directory root to snapshot root."""
    p = Path(root)
    if (p / CURRENT_DIR / POINTER_FILE_NAME).is_file():
        return p
    sub = p / DATASET / SNAPSHOTS_DIR
    if (sub / CURRENT_DIR / POINTER_FILE_NAME).is_file() or sub.is_dir():
        return sub
    return p


def get_active_accession(
    snapshots_root: Path | str,
    accession: str,
    *,
    branch_name: str | None = None,
    profile: RuntimeResourceProfile | None = None,
) -> dict[str, Any] | None:
    """Return active accession record or None if absent."""
    root = _resolve_snapshots_root(snapshots_root)
    ptr = read_pointer(root, branch_name=branch_name)
    if ptr is None:
        return None
    lineage = walk_lineage(root, str(ptr["snapshot_id"]))
    con = connect(profile)
    try:
        rows = query_point(
            con,
            INVENTORY_ACCESSIONS_SPEC,
            lineage,
            root,
            accession,
            key_column="accession",
            all_specs=INVENTORY_RELATIONS,
        )
        return rows[0] if rows else None
    finally:
        con.close()


def get_active_entries(
    snapshots_root: Path | str,
    accession: str,
    *,
    branch_name: str | None = None,
    profile: RuntimeResourceProfile | None = None,
) -> list[dict[str, Any]]:
    """Return active entry records for an accession, masking superseded ones."""
    root = _resolve_snapshots_root(snapshots_root)
    ptr = read_pointer(root, branch_name=branch_name)
    if ptr is None:
        return []
    lineage = walk_lineage(root, str(ptr["snapshot_id"]))
    con = connect(profile)
    try:
        return query_point(
            con,
            INVENTORY_ENTRIES_SPEC,
            lineage,
            root,
            accession,
            key_column="accession",
            all_specs=INVENTORY_RELATIONS,
        )
    finally:
        con.close()


def get_accessions_by_cik(
    snapshots_root: Path | str,
    cik: str,
    *,
    branch_name: str | None = None,
    profile: RuntimeResourceProfile | None = None,
) -> list[dict[str, Any]]:
    """Return active accession records for a filing CIK."""
    root = _resolve_snapshots_root(snapshots_root)
    ptr = read_pointer(root, branch_name=branch_name)
    if ptr is None:
        return []
    lineage = walk_lineage(root, str(ptr["snapshot_id"]))
    con = connect(profile)
    try:
        return query_point(
            con,
            INVENTORY_ACCESSIONS_SPEC,
            lineage,
            root,
            cik,
            key_column="filing_cik",
            all_specs=INVENTORY_RELATIONS,
        )
    finally:
        con.close()


__all__ = [
    "get_accessions_by_cik",
    "get_active_accession",
    "get_active_entries",
]
