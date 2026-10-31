"""Policy-driven target planning for the filing catalog.
Quota fulfillment, stratification, and feature snapshot selection.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from edgar_sec.domain.filing_catalog.schemas import (
    LOCATOR_POLICY_COLUMNS,
    OCCURRENCE_FEATURE_COLUMNS,
    SCOPE_POLICY,
)
from edgar_sec.engine.selection.features import FeatureSnapshotBuilder
from edgar_sec.engine.selection.snapshot import SnapshotPaths
from edgar_sec.engine.selection.inventory import (
    InventoryStatistics,
    UnknownDimensionError,
)
from edgar_sec.engine.selection.policy import (
    SeedFiler,
    SelectionPolicy,
    compute_seed_fingerprint,
    era_bands_for_range,
    write_seed_filers_csv,
)
from edgar_sec.engine.selection.selector import DeficitSelector
from edgar_sec.foundation.runtime.paths import DATA_FILE_NAME
from edgar_sec.foundation.runtime.progress import ProgressCallback, emit_progress
from edgar_sec.foundation.runtime.settings.parquet import resolve_row_group_size
from edgar_sec.foundation.runtime.settings.runtime import resolve_read_batch_size
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.duckdb import (
    connect,
    copy_query_to_parquet,
    sql_literal,
)
from edgar_sec.pipelines.filing_catalog.cohort_seed import (
    SeedFilerSource,
    cohort_seed_filers,
)
from edgar_sec.pipelines.filing_catalog.discovery import (
    catalog_year_bounds,
    eligible_year_bounds,
    resolve_catalog_reference,
)
from edgar_sec.pipelines.filing_catalog.family_index import (
    resolve_active_family_index,
)
from edgar_sec.pipelines.filing_catalog.paths import (
    LOCATOR_GROUPS_FILE,
    PLAN_TARGETS_DIR,
    RESERVE_TARGETS_FILE,
    SEED_FILERS_FILE,
    FilingCatalogPaths,
    form_partition_directory,
    resolve_filing_catalog_paths,
)
from edgar_sec.pipelines.filing_catalog.publication import (
    TARGET_PLAN_SCHEMA_VERSION,
    plan_identity,
    reuse_existing_plan,
    staged_plan_bundle,
    write_plan_documents,
)
from .shared import (
    catalog_target_files,
    resolve_cohort,
)


def _policy_locator_groups_query(locator_source: str) -> str:
    """Project policy locators widened with stratification dimensions."""
    projection = ", ".join(f"l.{column}" for column in LOCATOR_POLICY_COLUMNS)
    return f"""
    SELECT {projection}
    FROM {locator_source}
    ORDER BY document_locator_key
    """


def _inventory_feasibility(
    snapshot: SnapshotPaths, policy: SelectionPolicy
) -> dict[str, Any]:
    """Predict whether selection policy quotas are meetable from inventory."""
    if not policy.floors and not policy.composites:
        return {"checked": False, "reason": "policy declares no floors or composites"}
    statistics = InventoryStatistics(snapshot.snapshot_dir)
    try:
        floors = (
            statistics.check_floor_feasibility(policy.floors) if policy.floors else {}
        )
        composites = (
            statistics.check_composite_feasibility(policy.composites)
            if policy.composites
            else []
        )
    except (UnknownDimensionError, OSError) as error:
        return {"checked": False, "reason": f"inventory unavailable: {error}"}
    return {
        "checked": True,
        "floors": floors,
        "composites": composites,
        "infeasible_floors": sorted(
            value
            for dimension in floors.values()
            for value, entry in dimension.items()
            if not entry["feasible"]
        ),
        "infeasible_composites": [
            entry["filters"] for entry in composites if not entry["feasible"]
        ],
    }


def _resolve_era_bands(
    paths: FilingCatalogPaths, catalog: str, policy: SelectionPolicy
) -> SelectionPolicy:
    """Return the policy carrying the era bands selection will use."""
    if not policy.derives_era_bands:
        return policy
    bounds = eligible_year_bounds(
        paths, catalog, forms=policy.forms, date_selection=policy.date_selection_clauses
    )
    if bounds is None:
        bounds = catalog_year_bounds(paths, catalog)
    return policy.with_era_bands(era_bands_for_range(*bounds))


def plan_policy(
    catalog: str,
    policy: SelectionPolicy,
    output_root: str | Path | None = None,
    *,
    seed_filers: dict[str, SeedFiler] | None = None,
    seed_filer_source: SeedFilerSource | None = None,
    seed_cohort: str | None = None,
    parent_locator_path: str | Path | None = None,
    progress: ProgressCallback = None,
    row_group_size: int | None = None,
) -> dict[str, Any]:
    """Publish one immutable policy-driven target-plan bundle."""
    row_group_size = resolve_row_group_size(row_group_size)
    if not policy.forms:
        raise ValueError("policy must configure at least one form")

    paths = (
        resolve_filing_catalog_paths(output_root)
        if output_root is not None
        else resolve_filing_catalog_paths()
    )
    catalog = resolve_catalog_reference(paths, catalog)
    active_target_parts = catalog_target_files(paths, catalog)

    policy = _resolve_era_bands(paths, catalog, policy)
    family_index, family_index_path = resolve_active_family_index(paths.artifacts_root)

    seed_cohort_input = resolve_cohort(paths.artifacts_root, seed_cohort)
    if seed_filer_source is not None:
        pinned_seed = {}
        resolved_seed_source = seed_filer_source
    elif seed_cohort_input is not None:
        seed_cohort_record, seed_cohort_dataset = seed_cohort_input
        pinned_seed = {}
        resolved_seed_source = cohort_seed_filers(
            seed_cohort_record, seed_cohort_dataset
        )
    else:
        pinned_seed = seed_filers or {}
        resolved_seed_source = None
    seed_fingerprint = (
        resolved_seed_source.fingerprint
        if resolved_seed_source is not None
        else compute_seed_fingerprint(pinned_seed)
    )
    seed_filer_count = (
        resolved_seed_source.count
        if resolved_seed_source is not None
        else len(pinned_seed)
    )
    request = {
        "catalog_id": catalog,
        "row_group_size": row_group_size,
        "scope": SCOPE_POLICY,
        "policy_fingerprint": policy.policy_fingerprint,
        "seed_fingerprint": seed_fingerprint,
        "family_index_id": family_index.family_index_id,
        "plan_schema_version": TARGET_PLAN_SCHEMA_VERSION,
    }
    if seed_cohort_input is not None:
        request["seed_cohort_id"] = seed_cohort_record.cohort_id
        request["seed_cohort_dataset_sha256"] = seed_cohort_record.dataset_sha256
    plan_id = plan_identity(request)
    final_dir = paths.plan_dir(plan_id)

    existing = reuse_existing_plan(final_dir, plan_id, SCOPE_POLICY)
    if existing is not None:
        emit_progress(
            progress,
            {"type": "merge_stage", "stage": "reuse_plan", "plan_id": plan_id},
        )
        return existing

    emit_progress(
        progress,
        {
            "type": "merge_stage",
            "stage": "policy_plan",
            "plan_id": plan_id,
            "catalog": catalog,
        },
    )

    emit_progress(
        progress,
        {
            "type": "merge_stage",
            "stage": "family_index_ready",
            "catalog": catalog,
            "family_index_id": family_index.family_index_id,
        },
    )
    dag_catalog = DAGCatalog(paths.snapshots_root)
    node = dag_catalog.get_manifest(catalog)
    delta_target_parts: tuple[Path, ...] = ()
    parent_feature_snapshot_id: str | None = None
    if node is not None and node.kind == "delta" and node.parent_snapshot_id:
        delta_target_parts = dag_catalog.resolve_relation(catalog, "filing_targets")
        parent_builder = FeatureSnapshotBuilder(
            target_root=paths.snapshot_targets_dir(node.parent_snapshot_id),
            profile_path=paths.snapshot_profiles_file(node.parent_snapshot_id),
            output_root=paths.catalog_root,
            policy=policy,
            family_index_path=family_index_path,
            family_index_id=family_index.family_index_id,
            row_group_size=row_group_size,
        )
        parent_feature_snapshot_id = parent_builder.snapshot_dir(
            sorted(set(policy.forms))
        ).name

    builder = FeatureSnapshotBuilder(
        target_root=paths.snapshot_targets_dir(catalog),
        profile_path=paths.snapshot_profiles_file(catalog),
        output_root=paths.catalog_root,
        policy=policy,
        family_index_path=family_index_path,
        family_index_id=family_index.family_index_id,
        row_group_size=row_group_size,
        parent_feature_snapshot_id=parent_feature_snapshot_id,
        active_target_parts=active_target_parts,
        delta_target_parts=delta_target_parts,
    )
    emit_progress(
        progress,
        {"type": "merge_stage", "stage": "features_started", "catalog": catalog},
    )
    snapshot = builder.build(progress=progress)
    emit_progress(
        progress,
        {
            "type": "merge_stage",
            "stage": "features_complete",
            "snapshot": snapshot.snapshot_dir.name,
        },
    )

    selector = DeficitSelector(
        snapshot.snapshot_dir,
        policy,
        seed_filers=pinned_seed,
        seed_cik_relation=(
            resolved_seed_source.cik_relation_sql
            if resolved_seed_source is not None
            else None
        ),
    )
    emit_progress(
        progress,
        {"type": "merge_stage", "stage": "selection_started", "catalog": catalog},
    )
    selection = selector.select(
        parent_locator_path=parent_locator_path, progress=progress
    )

    with staged_plan_bundle(final_dir, plan_id) as staging:
        targets_root = staging / PLAN_TARGETS_DIR
        targets_root.mkdir(parents=True, exist_ok=True)
        if resolved_seed_source is not None:
            resolved_seed_source.write_csv(staging / SEED_FILERS_FILE)
        else:
            write_seed_filers_csv(staging / SEED_FILERS_FILE, pinned_seed)

        with connect() as con:
            locator_source = (
                f"{snapshot.locator_relation} l "
                "JOIN read_parquet("
                f"{sql_literal(str(selection.active_keys_path))}) s "
                "ON l.document_locator_key = s.document_locator_key"
            )
            occurrence_source = (
                f"{snapshot.occurrence_relation} o "
                "JOIN read_parquet("
                f"{sql_literal(str(selection.active_keys_path))}) s "
                "ON o.document_locator_key = s.document_locator_key"
            )

            selected_forms = con.execute(
                f"SELECT DISTINCT form FROM ({occurrence_source}) ORDER BY form"
            ).to_arrow_reader(batch_size=resolve_read_batch_size())
            target_columns = ", ".join(
                f"o.{name}" for name in OCCURRENCE_FEATURE_COLUMNS
            )
            counts: dict[str, int] = {}
            total_rows = 0
            for form_batch in selected_forms:
                form_values = form_batch.column(0)
                for row_index in range(form_batch.num_rows):
                    form_name = str(form_values[row_index].as_py())
                    destination = (
                        targets_root
                        / form_partition_directory(form_name)
                        / DATA_FILE_NAME
                    )
                    query = (
                        f"SELECT {target_columns} FROM ({occurrence_source}) "
                        f"WHERE form = {sql_literal(form_name)} "
                        "ORDER BY o.document_locator_key, o.occurrence_id"
                    )
                    counts[form_name] = copy_query_to_parquet(
                        con, query, destination, row_group_size
                    )
                    total_rows += counts[form_name]
                    emit_progress(
                        progress,
                        {
                            "type": "merge_stage",
                            "stage": f"targets:{form_name}",
                            "rows": counts[form_name],
                        },
                    )

            locator_count = copy_query_to_parquet(
                con,
                _policy_locator_groups_query(locator_source),
                staging / LOCATOR_GROUPS_FILE,
                row_group_size,
            )

            if selection.reserve_count:
                copy_query_to_parquet(
                    con,
                    "SELECT l.* FROM "
                    f"{snapshot.locator_relation} l "
                    "JOIN read_parquet("
                    f"{sql_literal(str(selection.reserve_keys_path))}) r "
                    "ON l.document_locator_key = r.document_locator_key "
                    "ORDER BY l.document_locator_key",
                    staging / RESERVE_TARGETS_FILE,
                    row_group_size,
                )

        selection_report = {
            "scope": SCOPE_POLICY,
            "catalog_id": catalog,
            "plan_id": plan_id,
            "family_index_id": family_index.family_index_id,
            "active_targets_count": total_rows,
            "unique_locators_count": locator_count,
            "reserve_count": selection.reserve_count,
            "counts": counts,
            "inventory_feasibility": _inventory_feasibility(snapshot, policy),
            **{
                k: v
                for k, v in selection.report.items()
                if k != "coverage_distributions"
            },
        }
        plan_meta = {
            "plan_schema_version": TARGET_PLAN_SCHEMA_VERSION,
            "plan_id": plan_id,
            "catalog_id": catalog,
            "scope": SCOPE_POLICY,
            "family_index_id": family_index.family_index_id,
            "policy_corpus": policy.corpus_id,
            "policy_fingerprint": policy.policy_fingerprint,
            "seed_fingerprint": seed_fingerprint,
            "seed_filer_count": seed_filer_count,
            "level": policy.level,
            "target_units": policy.requested_units(),
            "parent_plan_id": policy.parent_plan_id,
            "forms": list(policy.forms),
            "document_suffixes": list(policy.document_suffixes),
            "counts": counts,
            "selected_rows": total_rows,
            "active_targets_count": total_rows,
            "unique_locators_count": locator_count,
            "reserve_count": selection.reserve_count,
            "underfilled_floors": selection.report["underfilled_floors"],
            "selection_policy": policy.to_dict(),
            "request_fingerprint": hashlib.sha256(
                json.dumps(request, sort_keys=True).encode("utf-8")
            ).hexdigest(),
        }
        if seed_cohort_input is not None:
            plan_meta["seed_cohort_id"] = seed_cohort_record.cohort_id
            plan_meta["seed_cohort_dataset_sha256"] = seed_cohort_record.dataset_sha256
        plan_meta = write_plan_documents(staging, plan_meta, selection_report)

    return plan_meta


__all__ = ["plan_policy"]
