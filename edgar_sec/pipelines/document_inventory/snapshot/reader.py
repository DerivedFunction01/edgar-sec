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
from edgar_sec.infra.storage.dag.query import (
    compile_pruned_views,
    derive_accession_range,
    query_point,
)
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


def get_accessions_by_source_cik(
    snapshots_root: Path | str,
    source_cik: str,
    *,
    branch_name: str | None = None,
    profile: RuntimeResourceProfile | None = None,
) -> list[dict[str, Any]]:
    """Return active accession records associated with a catalog source CIK."""
    root = _resolve_snapshots_root(snapshots_root)
    ptr = read_pointer(root, branch_name=branch_name)
    if ptr is None:
        return []
    lineage = walk_lineage(root, str(ptr["snapshot_id"]))
    con = connect(profile)
    try:
        compile_pruned_views(
            con,
            INVENTORY_RELATIONS,
            lineage,
            root,
            {"accession_sources": (source_cik, source_cik)},
        )
        cursor = con.execute(
            "SELECT a.* FROM active_accession_sources s "
            "JOIN active_accessions a ON s.accession = a.accession "
            "WHERE s.source_cik = ?",
            [source_cik],
        )
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        con.close()


def query_accessions(
    snapshots_root: Path | str,
    *,
    form: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    filing_cik: str | None = None,
    source_cik: str | None = None,
    limit: int | None = None,
    branch_name: str | None = None,
    profile: RuntimeResourceProfile | None = None,
) -> list[dict[str, Any]]:
    """Query active accessions by form, date range, filing CIK, and/or source CIK."""
    root = _resolve_snapshots_root(snapshots_root)
    ptr = read_pointer(root, branch_name=branch_name)
    if ptr is None:
        return []
    lineage = walk_lineage(root, str(ptr["snapshot_id"]))
    con = connect(profile)
    try:
        ranges: dict[str, tuple[str | None, str | None]] = {}
        if filing_cik is not None:
            r_min, r_max = derive_accession_range(filing_cik)
            ranges["accessions"] = (r_min, r_max)
        if source_cik is not None:
            ranges["accession_sources"] = (source_cik, source_cik)
        compile_pruned_views(con, INVENTORY_RELATIONS, lineage, root, ranges)

        params: list[Any] = []
        if source_cik is not None:
            query = (
                "SELECT a.* FROM active_accession_sources s "
                "JOIN active_accessions a ON s.accession = a.accession "
                "WHERE s.source_cik = ?"
            )
            params.append(source_cik)
        else:
            query = "SELECT a.* FROM active_accessions a"

        where: list[str] = []
        if form is not None:
            where.append("a.form = ?")
            params.append(form)
        if start_date is not None:
            where.append("a.filing_date >= ?")
            params.append(start_date)
        if end_date is not None:
            where.append("a.filing_date <= ?")
            params.append(end_date)
        if filing_cik is not None:
            where.append("a.filing_cik = ?")
            params.append(filing_cik)

        if where:
            query += " AND " + " AND ".join(where)
        query += " ORDER BY a.form, a.filing_date, a.accession"
        if limit is not None:
            query += " LIMIT ?"
            params.append(int(limit))

        cursor = con.execute(query, params)
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        con.close()


def get_accession_bundle(
    snapshots_root: Path | str,
    accession: str,
    *,
    branch_name: str | None = None,
    profile: RuntimeResourceProfile | None = None,
) -> dict[str, Any] | None:
    """Resolve accession metadata, active child entries, and source CIKs."""
    root = _resolve_snapshots_root(snapshots_root)
    ptr = read_pointer(root, branch_name=branch_name)
    if ptr is None:
        return None
    lineage = walk_lineage(root, str(ptr["snapshot_id"]))
    con = connect(profile)
    try:
        compile_pruned_views(con, INVENTORY_RELATIONS, lineage, root)
        acc_cursor = con.execute(
            "SELECT * FROM active_accessions WHERE accession = ?", [accession]
        )
        acc_columns = [desc[0] for desc in acc_cursor.description]
        acc_rows = acc_cursor.fetchall()
        if not acc_rows:
            return None
        accession_record = dict(zip(acc_columns, acc_rows[0]))

        ent_cursor = con.execute(
            "SELECT * FROM active_entries WHERE accession = ?", [accession]
        )
        ent_columns = [desc[0] for desc in ent_cursor.description]
        entries = [dict(zip(ent_columns, row)) for row in ent_cursor.fetchall()]

        src_cursor = con.execute(
            "SELECT source_cik FROM active_accession_sources WHERE accession = ?",
            [accession],
        )
        source_ciks = [row[0] for row in src_cursor.fetchall()]

        return {
            "accession": accession_record,
            "entries": entries,
            "source_ciks": source_ciks,
        }
    finally:
        con.close()


__all__ = [
    "get_accessions_by_cik",
    "get_accessions_by_source_cik",
    "get_active_accession",
    "get_active_entries",
    "get_accession_bundle",
    "query_accessions",
]
