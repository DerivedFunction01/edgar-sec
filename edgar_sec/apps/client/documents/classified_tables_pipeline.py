"""Classified tables, pipeline version: many filings, from the store (D2).

Read-only over the published table-classification DAG store: the branch
tip is resolved through the DAG catalog, never by directory guess.
Absent store or filing is honest absence, never a compute fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from edgar_sec.apps.client.documents.classified_tables import ClassifiedTable
from edgar_sec.domain.document.aggregate import FilingAggregate
from edgar_sec.foundation.runtime import paths as foundation_paths
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.paths import DAGPaths
from edgar_sec.infra.storage.dag.publication import read_pointer
from edgar_sec.infra.storage.duckdb import connect, sql_path_list

#: Store contract names; the one place the store shape is spelled.
STORE_DIR = "table_classification"
REL_RUN_PROVENANCE = "run_provenance"
REL_FILINGS = "filings"
REL_FILING_RECORDS = "filing_records"
REL_GEOMETRY_INVENTORY = "geometry_inventory"
REL_CLASSIFICATIONS = "classifications"

_ORIGIN = "pipeline"
_BRANCH = "main"


@dataclass(frozen=True, slots=True)
class PipelineClassifiedTables:
    """Rows for one filing plus the store provenance that produced them."""

    tables: tuple[ClassifiedTable, ...]
    store_present: bool
    filing_present: bool
    snapshot_id: str | None
    source_snapshot_id: str | None
    plan_id: str | None
    registry_state: str | None
    normalize_version: str | None
    renderer_version: str | None
    plan_format_version: str | None
    run_output_version: str | None
    stamp: str | None
    classified_count: int | None = None
    origin: str = _ORIGIN


def default_store_root(artifacts_root: Path | str | None = None) -> Path:
    """Resolve the published store's dataset root under an artifacts root."""
    if artifacts_root is not None:
        return Path(artifacts_root) / STORE_DIR
    from edgar_sec.foundation.runtime.paths import resolve_paths

    return resolve_paths().artifacts_root / STORE_DIR


def _stamp(
    registry_state: str | None, normalize: str | None, renderer: str | None
) -> str | None:
    """Build the shared stamp from the store provenance (classified-v1)."""
    if not registry_state or not normalize or not renderer:
        return None
    registry = registry_state.removeprefix("sha256:")
    return (
        f"classified-v1;registry={registry};normalize={normalize};renderer={renderer}"
    )


def _absent() -> PipelineClassifiedTables:
    """The honest-absence result: no store published at the root."""
    return PipelineClassifiedTables(
        tables=(),
        store_present=False,
        filing_present=False,
        snapshot_id=None,
        source_snapshot_id=None,
        plan_id=None,
        registry_state=None,
        normalize_version=None,
        renderer_version=None,
        plan_format_version=None,
        run_output_version=None,
        stamp=None,
    )


def _tip(snapshots_root: Path) -> str | None:
    """The store branch tip snapshot id, or ``None`` when unpublished."""
    if not DAGPaths(snapshots_root).catalog_file.is_file():
        return None
    pointer = read_pointer(snapshots_root, _BRANCH)
    return str(pointer["snapshot_id"]) if pointer else None


def _parts(snapshots_root: Path, tip: str, relation: str) -> tuple[Path, ...]:
    """The tip lineage's active parts for one relation (empty if none)."""
    catalog = DAGCatalog(snapshots_root, read_only=True)
    try:
        return catalog.resolve_active_relation(
            tip, relation, relative_to=snapshots_root
        )
    except ValueError:
        return ()


def classified_tables_pipeline(
    filing: FilingAggregate | str,
    *,
    store_root: Path | str | None = None,
    artifacts_root: Path | str | None = None,
) -> PipelineClassifiedTables:
    """Serve one filing's classified tables from the published store."""
    accession = (
        filing.accession.value if isinstance(filing, FilingAggregate) else str(filing)
    )
    root = (
        Path(store_root)
        if store_root is not None
        else default_store_root(artifacts_root)
    )
    snapshots_root = root / foundation_paths.SNAPSHOTS_DIR
    tip = _tip(snapshots_root)
    if tip is None:
        return _absent()
    provenance_parts = _parts(snapshots_root, tip, REL_RUN_PROVENANCE)
    if not provenance_parts:
        return _absent()
    con = connect()
    try:
        table = f"read_parquet({sql_path_list([str(p) for p in provenance_parts])})"
        rows = con.execute(
            "SELECT store_snapshot_id, source_snapshot_id, plan_id, "
            "registry_state, normalize_version, renderer_version, "
            f"plan_format_version, run_output_version FROM {table} LIMIT 1"
        ).fetchall()
        if not rows:
            return _absent()
        values = tuple(str(value) if value is not None else None for value in rows[0])
        snapshot_id, source_snapshot_id, plan_id, registry_state = values[:4]
        normalize_v, renderer_v, plan_format, run_output_v = values[4:]
        stamp = _stamp(registry_state, normalize_v, renderer_v)
        filing_present = False
        classified_count: int | None = None
        record_parts = _parts(snapshots_root, tip, REL_FILING_RECORDS)
        if record_parts:
            table = f"read_parquet({sql_path_list([str(p) for p in record_parts])})"
            found = con.execute(
                f"SELECT classified_count FROM {table} WHERE accession = ?",
                [accession],
            ).fetchone()
            if found is not None:
                filing_present = True
                if found[0] is not None:
                    classified_count = int(found[0])
        tables: tuple[ClassifiedTable, ...] = ()
        classification_parts = _parts(snapshots_root, tip, REL_CLASSIFICATIONS)
        inventory_parts = _parts(snapshots_root, tip, REL_GEOMETRY_INVENTORY)
        if classification_parts and inventory_parts:
            classifications = (
                f"read_parquet({sql_path_list([str(p) for p in classification_parts])})"
            )
            inventory = (
                f"read_parquet({sql_path_list([str(p) for p in inventory_parts])})"
            )
            rows = con.execute(
                "SELECT c.table_index, c.source_document, c.family, c.tier, "
                f"c.score FROM {classifications} c JOIN {inventory} g "
                "ON g.accession = c.accession "
                "AND g.source_document = c.source_document "
                "AND g.table_index = c.table_index "
                "WHERE c.accession = ? "
                "ORDER BY c.source_document, c.table_index",
                [accession],
            ).fetchall()
            tables = tuple(
                ClassifiedTable(
                    table_index=int(row[0]),
                    source_document=str(row[1]) if row[1] is not None else None,
                    family=str(row[2]),
                    tier=str(row[3]),
                    score=float(row[4]),
                    origin=_ORIGIN,
                    stamp=stamp or "",
                )
                for row in rows
            )
    finally:
        con.close()
    return PipelineClassifiedTables(
        tables=tables,
        store_present=True,
        filing_present=filing_present,
        snapshot_id=snapshot_id,
        source_snapshot_id=source_snapshot_id,
        plan_id=plan_id,
        registry_state=registry_state,
        normalize_version=normalize_v,
        renderer_version=renderer_v,
        plan_format_version=plan_format,
        run_output_version=run_output_v,
        stamp=stamp,
        classified_count=classified_count,
    )


__all__ = [
    "REL_CLASSIFICATIONS",
    "REL_FILING_RECORDS",
    "REL_FILINGS",
    "REL_GEOMETRY_INVENTORY",
    "REL_RUN_PROVENANCE",
    "STORE_DIR",
    "PipelineClassifiedTables",
    "classified_tables_pipeline",
    "default_store_root",
]
