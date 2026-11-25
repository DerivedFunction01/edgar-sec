"""Bounded projection of published catalog plans into transient work orders."""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from edgar_sec.domain.document_inventory.schemas import ENTRY_SCHEMA_VERSION
from edgar_sec.engine.filing_summary.parser import ENUMERATOR_FINGERPRINT
from edgar_sec.engine.index_pages.parser import PARSER_FINGERPRINT
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.runtime.paths import PLAN_FILE_NAME
from edgar_sec.foundation.runtime.resources import (
    RuntimeResourceProfile,
    derive_resources,
)
from edgar_sec.foundation.runtime.settings import resolve_settings
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.infra.storage.duckdb import (
    connect,
    copy_query_to_parquet,
    sql_literal,
)
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.pipelines.document_inventory.cohort import (
    CohortInputError,
)
from edgar_sec.pipelines.document_inventory.paths import (
    COHORT_ACCESSIONS_FILE,
    COHORT_SOURCES_FILE,
    FilingCatalogPaths,
    InventoryRunPaths,
    LOCATOR_GROUPS_FILE,
    PROJECTION_MANIFEST_FILE,
    WORK_ORDER_FILE,
    inventory_paths,
    inventory_run_paths,
    resolve_filing_catalog_paths,
)
from edgar_sec.pipelines.document_inventory.run_state.run_manifest import (
    ManifestMismatchError,
    WORK_ORDER_VERSION,
    validate_work_order,
    write_work_order,
)
from edgar_sec.pipelines.document_inventory.snapshot.contracts.errors import (
    BaseSnapshotError,
)
from edgar_sec.pipelines.document_inventory.snapshot.projection.projection_inputs import (
    base_snapshot_parts,
    catalog_plan_parts,
)
from edgar_sec.pipelines.document_inventory.snapshot.projection.projection_manifest import (
    intent_id,
    read_projection_manifest,
    run_manifest,
)
from edgar_sec.pipelines.document_inventory.snapshot.projection.projection_relations import (
    COHORT_ACCESSIONS_SCHEMA,
    COHORT_SOURCES_SCHEMA,
    hash_relations,
    validate_output_schema,
    work_items,
)
from edgar_sec.pipelines.document_inventory.snapshot.projection.projection_staging import (
    build_work_candidates,
    check_metadata_against_base,
    normalize_observations,
    stage_base_accessions,
    stage_cohort_tables,
    stage_plan_targets,
)
from edgar_sec.pipelines.document_inventory.snapshot.contracts.schema import (
    LOOKUP_LAYOUT_VERSION,
    SNAPSHOT_RELATION_VERSION,
)

__all__ = ["PrefetchProjection", "project_catalog_plan"]

_ARCHIVE_BASE_URL = "https://www.sec.gov/Archives/edgar/data"


@dataclass(frozen=True, slots=True)
class PrefetchProjection:
    run_id: str
    catalog_plan_id: str
    base_snapshot_id: str | None
    cohort_fingerprint: str
    work_order_digest: str
    work_order_rows: int
    explicit_refresh_salt: str | None
    paths: InventoryRunPaths


def _validate_existing_projection(
    paths: InventoryRunPaths,
    expected: dict[str, Any],
    *,
    plan_id: str,
    base_snapshot_id: str | None,
    chunk_size: int,
    explicit_refresh: bool,
) -> PrefetchProjection:
    manifest_path = paths.projection_manifest_path()
    manifest = read_projection_manifest(manifest_path)
    comparable = {
        key: value for key, value in expected.items() if key not in {"outputs"}
    }
    actual = {key: value for key, value in manifest.items() if key not in {"outputs"}}
    if actual != comparable:
        raise ManifestMismatchError(f"projection identity mismatch for {paths.run_id}")
    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict):
        raise ManifestMismatchError("projection output metadata is missing")
    output_paths = {
        "cohort_accessions": paths.cohort_accessions_path(),
        "cohort_sources": paths.cohort_sources_path(),
        "work_order": paths.work_order_path(),
    }
    for name, path in output_paths.items():
        record = outputs.get(name)
        if not isinstance(record, dict) or not path.is_file():
            raise ManifestMismatchError(f"projection output missing: {name}")
        if record.get("path") != path.name:
            raise ManifestMismatchError(f"projection output path mismatch: {name}")
        if file_sha256(path) != record.get("sha256"):
            raise ManifestMismatchError(f"projection output digest mismatch: {name}")
    validate_output_schema(paths.cohort_accessions_path(), COHORT_ACCESSIONS_SCHEMA)
    validate_output_schema(paths.cohort_sources_path(), COHORT_SOURCES_SCHEMA)
    cohort_fingerprint = hash_relations(
        paths.cohort_accessions_path(), paths.cohort_sources_path()
    )
    if cohort_fingerprint != manifest.get("cohort_fingerprint"):
        raise ManifestMismatchError("projection cohort fingerprint mismatch")
    work_identity = validate_work_order(paths.work_order_path())
    if work_identity.digest != manifest.get(
        "work_order_digest"
    ) or work_identity.row_count != manifest.get("work_order_rows"):
        raise ManifestMismatchError("projection work-order identity mismatch")
    run_manifest(
        paths,
        base_snapshot_id=base_snapshot_id,
        plan_id=plan_id,
        cohort_fingerprint=cohort_fingerprint,
        chunk_size=chunk_size,
        explicit_refresh=explicit_refresh,
        work_order_path=paths.work_order_path(),
    )
    return PrefetchProjection(
        paths.run_id,
        plan_id,
        base_snapshot_id,
        cohort_fingerprint,
        work_identity.digest,
        work_identity.row_count,
        manifest.get("explicit_refresh_salt"),
        paths,
    )


def project_catalog_plan(
    catalog_plan_id: str,
    *,
    artifacts_root: Path | str,
    catalog_paths: FilingCatalogPaths | None = None,
    profile: RuntimeResourceProfile | None = None,
    archive_base_url: str = _ARCHIVE_BASE_URL,
    chunk_size: int | None = None,
    explicit_refresh: bool = False,
    explicit_refresh_salt: str | None = None,
    base_snapshot_id: str | None = None,
    branch_name: str = "main",
) -> PrefetchProjection:
    """Persist the full cohort projection and pre-fetch missing-accession work order.
    ``base_snapshot_id`` selects the lineage base; an explicit base must match the
    branch tip, so historical bases require a branch created at that tip first.
    """
    if not archive_base_url.startswith(("https://", "http://")):
        raise ValueError("archive_base_url must be an HTTP(S) URL")
    if explicit_refresh_salt is not None and (
        not explicit_refresh or not explicit_refresh_salt
    ):
        raise ValueError("explicit_refresh_salt requires explicit_refresh and a value")
    refresh_salt = explicit_refresh_salt or (
        uuid.uuid4().hex if explicit_refresh else None
    )
    settings = resolve_settings(include=["runtime"])
    effective_chunk_size = int(
        settings["runtime.chunk_size"] if chunk_size is None else chunk_size
    )
    if effective_chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    resources = profile or derive_resources()
    resolved_catalog_paths = catalog_paths or resolve_filing_catalog_paths(
        artifacts_root
    )
    plan_root, plan, parts, plan_file_sha, locator_file_sha = catalog_plan_parts(
        catalog_plan_id, resolved_catalog_paths
    )
    locator_path = plan_root / LOCATOR_GROUPS_FILE
    base_paths = inventory_paths(artifacts_root)

    if base_snapshot_id is not None:
        catalog = DAGCatalog(base_paths.snapshots_root)
        current = catalog.read_pointer(branch_name)
        observed_tip = str(current["snapshot_id"]) if current else None
        if observed_tip != base_snapshot_id:
            raise BaseSnapshotError(
                f"base snapshot {base_snapshot_id!r} does not match the tip of "
                f"branch {branch_name!r} ({observed_tip!r}); create a branch at the "
                "requested base with 'inventory dag branch create --from <id>' "
                "before publishing there"
            )
    snapshot_id, base_parts, base_manifest_sha = base_snapshot_parts(
        base_paths, snapshot_id=base_snapshot_id, branch_name=branch_name
    )
    pinned_base_snapshot_id = snapshot_id
    source_id = f"plan:{catalog_plan_id}"

    staging_parent = base_paths.projection_staging_root
    staging_parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(tempfile.mkdtemp(prefix="projection-", dir=staging_parent))
    connection = None
    stage_complete = False
    try:
        connection = connect(resources)
        stage_plan_targets(connection, parts, plan, locator_path)
        normalize_observations(connection)
        stage_cohort_tables(connection)
        stage_base_accessions(connection, base_parts)
        check_metadata_against_base(connection)
        base_url = build_work_candidates(
            connection,
            archive_base_url=archive_base_url,
            explicit_refresh=explicit_refresh,
        )

        accessions_stage = staging_root / COHORT_ACCESSIONS_FILE
        sources_stage = staging_root / COHORT_SOURCES_FILE
        work_order_stage = staging_root / WORK_ORDER_FILE
        accession_count = copy_query_to_parquet(
            connection,
            "SELECT accession, filing_cik, form, filing_date, report_date, index_url "
            "FROM cohort_accessions_with_url ORDER BY accession",
            accessions_stage,
            schema=COHORT_ACCESSIONS_SCHEMA,
        )
        source_count = copy_query_to_parquet(
            connection,
            f"SELECT accession, source_cik, {sql_literal(source_id)} AS first_seen_by FROM cohort_sources ORDER BY source_cik, accession",
            sources_stage,
            schema=COHORT_SOURCES_SCHEMA,
        )
        work_identity = write_work_order(work_order_stage, work_items(connection))
        validate_output_schema(accessions_stage, COHORT_ACCESSIONS_SCHEMA)
        validate_output_schema(sources_stage, COHORT_SOURCES_SCHEMA)
        if (
            file_sha256(plan_root / PLAN_FILE_NAME) != plan_file_sha
            or file_sha256(locator_path) != locator_file_sha
            or any(file_sha256(path) != digest for _form, path, _count, digest in parts)
            or any(file_sha256(path) != digest for path, _count, digest in base_parts)
            or (
                pinned_base_snapshot_id is not None
                and DAGCatalog(base_paths.snapshots_root).get_manifest_sha256(
                    pinned_base_snapshot_id
                )
                != base_manifest_sha
            )
        ):
            raise CohortInputError(
                "invalid_bundle",
                detail="published catalog plan changed during projection",
            )
        cohort_fingerprint = hash_relations(accessions_stage, sources_stage)
        run_id = intent_id(
            catalog_id=str(plan["catalog_id"]),
            catalog_plan_id=catalog_plan_id,
            base_snapshot_id=pinned_base_snapshot_id,
            base_manifest_sha256=base_manifest_sha,
            cohort_fingerprint=cohort_fingerprint,
            chunk_size=effective_chunk_size,
            refresh_salt=refresh_salt,
        )
        input_parts = [
            {
                "form": form,
                "path": path.relative_to(plan_root).as_posix(),
                "row_count": count,
                "sha256": digest,
            }
            for form, path, count, digest in parts
        ]
        projection_manifest = {
            "projection_version": "1",
            "run_id": run_id,
            "catalog_plan_id": catalog_plan_id,
            "catalog_id": str(plan["catalog_id"]),
            "scope": plan["scope"],
            "plan_schema_version": plan["plan_schema_version"],
            "plan_sha256": plan_file_sha,
            "locator_groups_sha256": locator_file_sha,
            "target_parts": input_parts,
            "base_snapshot_id": pinned_base_snapshot_id,
            "base_manifest_sha256": base_manifest_sha,
            "base_accession_parts": [
                {
                    "path": str(path.relative_to(base_paths.snapshots_root)),
                    "row_count": row_count,
                    "sha256": digest,
                }
                for path, row_count, digest in base_parts
            ],
            "parser_version": PARSER_FINGERPRINT,
            "enumerator_version": ENUMERATOR_FINGERPRINT,
            "snapshot_relation_version": SNAPSHOT_RELATION_VERSION,
            "entry_schema_version": ENTRY_SCHEMA_VERSION,
            "lookup_layout_version": LOOKUP_LAYOUT_VERSION,
            "cohort_fingerprint": cohort_fingerprint,
            "cohort_accession_rows": accession_count,
            "cohort_source_rows": source_count,
            "work_order_digest": work_identity.digest,
            "work_order_rows": work_identity.row_count,
            "work_order_version": WORK_ORDER_VERSION,
            "chunk_size": effective_chunk_size,
            "explicit_refresh": explicit_refresh,
            "explicit_refresh_salt": refresh_salt,
            "archive_base_url": base_url,
            "outputs": {
                "cohort_accessions": {
                    "path": COHORT_ACCESSIONS_FILE,
                    "sha256": file_sha256(accessions_stage),
                },
                "cohort_sources": {
                    "path": COHORT_SOURCES_FILE,
                    "sha256": file_sha256(sources_stage),
                },
                "work_order": {
                    "path": WORK_ORDER_FILE,
                    "sha256": file_sha256(work_order_stage),
                },
            },
        }
        atomic_write_json(staging_root / PROJECTION_MANIFEST_FILE, projection_manifest)
        stage_complete = True
    finally:
        if connection is not None:
            connection.close()
        if not stage_complete:
            shutil.rmtree(staging_root, ignore_errors=True)

    run_paths = inventory_run_paths(artifacts_root, run_id)
    try:
        if run_paths.run_root.exists():
            projection = _validate_existing_projection(
                run_paths,
                projection_manifest,
                plan_id=catalog_plan_id,
                base_snapshot_id=pinned_base_snapshot_id,
                chunk_size=effective_chunk_size,
                explicit_refresh=explicit_refresh,
            )
            return projection
        run_paths.run_root.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging_root, run_paths.run_root)
        run_manifest(
            run_paths,
            base_snapshot_id=pinned_base_snapshot_id,
            plan_id=catalog_plan_id,
            cohort_fingerprint=cohort_fingerprint,
            chunk_size=effective_chunk_size,
            explicit_refresh=explicit_refresh,
            work_order_path=run_paths.work_order_path(),
        )
        return PrefetchProjection(
            run_id,
            catalog_plan_id,
            pinned_base_snapshot_id,
            cohort_fingerprint,
            work_identity.digest,
            work_identity.row_count,
            refresh_salt,
            run_paths,
        )
    finally:
        if staging_root.exists():
            shutil.rmtree(staging_root, ignore_errors=True)
