"""Production builder: connects projection, S4, and S5 into one pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from edgar_sec.engine.index_pages.parser import PARSER_FINGERPRINT
from edgar_sec.foundation.runtime.memory import reclaim
from edgar_sec.foundation.runtime.resources import (
    RuntimeResourceProfile,
    derive_resources,
)
from edgar_sec.foundation.runtime.settings import resolve_settings
from edgar_sec.infra.storage.duckdb import connect, sql_path_list
from edgar_sec.pipelines.document_inventory.coordinator import (
    run_missing_accessions,
)
from edgar_sec.pipelines.document_inventory.paths import (
    InventoryPaths,
    inventory_run_paths,
)
from edgar_sec.pipelines.document_inventory.run_manifest import (
    WORK_ORDER_VERSION,
    read_run_manifest,
)
from edgar_sec.pipelines.document_inventory.snapshot.models import (
    SnapshotPublication,
)
from edgar_sec.pipelines.document_inventory.snapshot.projection import (
    PrefetchProjection,
    project_catalog_plan,
)
from edgar_sec.pipelines.document_inventory.snapshot.validation import (
    validate_snapshot,
)
from edgar_sec.pipelines.document_inventory.snapshot.writer import (
    publish_committed_chunks,
)
from edgar_sec.foundation.runtime.paths import resolve_paths

__all__ = ["build_inventory"]


def _effective_chunk_size(chunk_size: int | None) -> int:
    settings = resolve_settings(include=["runtime"])
    effective = int(
        chunk_size if chunk_size is not None else settings["runtime.chunk_size"]
    )
    if effective < 1:
        raise ValueError("chunk_size must be positive")
    return effective


def _run_identity(projection: PrefetchProjection, chunk_size: int) -> dict[str, Any]:
    return {
        "parent_snapshot_id": projection.base_snapshot_id or "",
        "canonical_cohort_id": projection.cohort_fingerprint,
        "source_identity": f"filing-catalog-plan:{projection.catalog_plan_id}",
        "parser_version": PARSER_FINGERPRINT,
        "chunk_size": chunk_size,
        "refresh_mode": "force" if projection.explicit_refresh_salt else "normal",
        "fetch_mode": "force_refresh" if projection.explicit_refresh_salt else "live",
        "fixture_id": None,
        "work_order_version": WORK_ORDER_VERSION,
    }


def _has_new_source_edges(
    inventory_paths: InventoryPaths,
    parent_id: str,
    cohort_sources_path: Path,
    resources: RuntimeResourceProfile,
) -> bool:
    """Check whether the cohort introduces unseen (accession, source_cik) edges."""
    from edgar_sec.infra.storage.dag.query import compile_pruned_views
    from edgar_sec.infra.storage.dag.traversal import walk_lineage
    from edgar_sec.pipelines.document_inventory.snapshot.specs import (
        INVENTORY_RELATIONS,
    )

    con = connect(resources)
    try:
        lineage = walk_lineage(inventory_paths.snapshots_root, parent_id)
        compile_pruned_views(
            con,
            INVENTORY_RELATIONS,
            lineage,
            inventory_paths.snapshots_root,
        )
        cohort_parquet = sql_path_list([str(cohort_sources_path)])
        con.execute(
            f"CREATE TEMP VIEW cohort_sources AS SELECT * FROM "
            f"read_parquet({cohort_parquet}, hive_partitioning=false)"
        )
        cursor = con.execute(
            "SELECT count(*) FROM cohort_sources s "
            "WHERE NOT EXISTS ("
            "  SELECT 1 FROM active_accession_sources p "
            "  WHERE p.accession = s.accession AND p.source_cik = s.source_cik"
            ")"
        )
        return cursor.fetchone()[0] > 0
    finally:
        con.close()


def build_inventory(
    catalog_plan_id: str,
    *,
    base_snapshot_id: str | None = None,
    explicit_refresh: bool = False,
    chunk_size: int | None = None,
    retry_failures: bool = False,
    http_client: Any | None = None,
    profile: RuntimeResourceProfile | None = None,
    artifacts_root: Path | str | None = None,
    workers: int | None = None,
) -> SnapshotPublication:
    """Connect projection, S4, and S5 into a single deterministic build pipeline."""
    resolved_root = (
        Path(artifacts_root)
        if artifacts_root is not None
        else resolve_paths().artifacts_root
    )
    inventory_paths = InventoryPaths(resolved_root)
    resources = profile or derive_resources()
    effective_chunk_size = _effective_chunk_size(chunk_size)

    # Step 1: Plan validation & projection
    projection = project_catalog_plan(
        catalog_plan_id,
        artifacts_root=resolved_root,
        profile=resources,
        explicit_refresh=explicit_refresh,
        chunk_size=effective_chunk_size,
    )

    # Step 2: No-op & delta inspection
    if projection.work_order_rows == 0:
        parent_id = projection.base_snapshot_id
        if parent_id is not None:
            cohort_sources = Path(projection.paths.cohort_sources_path())
            if not _has_new_source_edges(
                inventory_paths, parent_id, cohort_sources, resources
            ):
                parent_manifest_path = inventory_paths.snapshot_manifest_path(parent_id)
                if parent_manifest_path.is_file():
                    parent_metadata = validate_snapshot(inventory_paths, parent_id)
                    return SnapshotPublication.no_op(parent_metadata)
                return SnapshotPublication.no_op(None)
        else:
            return SnapshotPublication.no_op(None)

    # Step 3: S4 Coordinator execution
    run_paths = inventory_run_paths(resolved_root, projection.run_id)
    identity = _run_identity(projection, effective_chunk_size)

    summary = run_missing_accessions(
        projection.paths.work_order_path(),
        identity,
        projection.paths,
        http_client=http_client,
        profile=resources,
        workers=workers,
        retry_failures=retry_failures,
    )

    if summary.refusal_count > 0 or summary.cancelled:
        return SnapshotPublication.failed(
            reason=f"{summary.refusal_count} work items refused or failed"
        )

    # Step 4: S5 Publication
    run_manifest = read_run_manifest(run_paths)
    if run_manifest is None:
        return SnapshotPublication.failed(
            reason="S4 run manifest missing after successful execution"
        )

    publication = publish_committed_chunks(
        run_paths,
        run_manifest,
        cohort_accessions_path=projection.paths.cohort_accessions_path(),
        cohort_sources_path=projection.paths.cohort_sources_path(),
        expected_parent_snapshot_id=projection.base_snapshot_id,
        profile=resources,
    )

    if publication.was_published and publication.snapshot is not None:
        reclaim()

    return publication
