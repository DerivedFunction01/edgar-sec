"""Bounded merge and pointer-last publication of validated attempts."""

from __future__ import annotations

import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from edgar_sec.domain.document_inventory.schemas import ENTRY_SCHEMA_VERSION
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.runtime.paths import snapshot_id_for
from edgar_sec.foundation.runtime.resources import RuntimeResourceProfile
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.manifest import (
    DAGNodeManifest,
    ParentRef,
    PartDescriptor,
)
from edgar_sec.infra.storage.dag.working.publication import (
    PublicationLock,
    StaleParentError,
    publish_node,
)
from edgar_sec.infra.storage.duckdb import connect
from edgar_sec.pipelines.document_inventory.paths import (
    InventoryPaths,
    InventoryRunPaths,
)
from edgar_sec.pipelines.document_inventory.run_state.run_manifest import (
    InventoryRunManifest,
    read_run_manifest,
)
from edgar_sec.pipelines.document_inventory.snapshot.publication.anti_join import (
    StagingRelations,
    anti_join,
)
from edgar_sec.pipelines.document_inventory.snapshot.publication.attempt_staging import (
    _copy_committed_attempts,
    _validate_input,
)
from edgar_sec.pipelines.document_inventory.snapshot.contracts.errors import (
    ValidationFailedError,
)
from edgar_sec.pipelines.document_inventory.snapshot.publication.installation import (
    _make_parent_input_dirs,
)
from edgar_sec.pipelines.document_inventory.snapshot.relations.merge_relations import (
    _create_merge_relations,
)
from edgar_sec.pipelines.document_inventory.snapshot.contracts.models import (
    SnapshotPublication,
)
from edgar_sec.pipelines.document_inventory.snapshot.projection.projection_relations import (
    COHORT_ACCESSIONS_SCHEMA,
)
from edgar_sec.pipelines.document_inventory.snapshot.relations.relation_parts import (
    _write_relation_part,
)
from edgar_sec.pipelines.document_inventory.snapshot.contracts.schema import (
    SNAPSHOT_ACCESSION_SOURCES_SCHEMA,
    SNAPSHOT_RELATION_VERSION,
)
from edgar_sec.pipelines.document_inventory.snapshot.contracts.specs import (
    INVENTORY_ACCESSIONS_SPEC,
    INVENTORY_ACCESSION_SOURCES_SPEC,
    INVENTORY_ENTRIES_SPEC,
    INVENTORY_ENUMERATION_SPEC,
    INVENTORY_RELATIONS,
)
from edgar_sec.pipelines.document_inventory.snapshot.publication.validation import (
    validate_snapshot,
)

__all__ = ["publish_committed_chunks"]


def publish_committed_chunks(
    run_paths: InventoryRunPaths,
    run: InventoryRunManifest,
    *,
    cohort_accessions_path: Path | str,
    cohort_sources_path: Path | str,
    expected_parent_snapshot_id: str | None,
    branch_name: str = "main",
    expected_branch_tip: str | None = None,
    profile: RuntimeResourceProfile | None = None,
) -> SnapshotPublication:
    """Merge a run's complete validated attempts into an immutable snapshot via a
    CAS pointer update under an exclusive publication lock.
    """
    if run.run_id != run_paths.run_id:
        raise ValidationFailedError("run manifest identity differs from its paths")
    if read_run_manifest(run_paths) != run:
        raise ValidationFailedError("run manifest differs from its persisted identity")
    if run.parent_snapshot_id != (expected_parent_snapshot_id or ""):
        raise ValidationFailedError("expected parent differs from the pinned run")
    cohort_accessions = Path(cohort_accessions_path).resolve()
    cohort_sources = Path(cohort_sources_path).resolve()
    _validate_input(cohort_accessions, COHORT_ACCESSIONS_SCHEMA, "cohort accessions")
    _validate_input(cohort_sources, SNAPSHOT_ACCESSION_SOURCES_SCHEMA, "cohort sources")
    inventory_paths = InventoryPaths(run_paths.artifacts_root)

    current = DAGCatalog(inventory_paths.snapshots_root).read_pointer(branch_name)
    observed_tip = str(current["snapshot_id"]) if current else None
    if expected_parent_snapshot_id is not None:
        if expected_parent_snapshot_id != observed_tip:
            raise StaleParentError(
                f"delta parent {expected_parent_snapshot_id!r} must match the tip of "
                f"branch {branch_name!r} ({observed_tip!r}); refresh the base or "
                "publish to a branch created at the base"
            )
    if expected_branch_tip is None:
        expected_branch_tip = observed_tip
    current_id = observed_tip
    if current_id != expected_parent_snapshot_id:
        raise StaleParentError(
            f"expected parent {expected_parent_snapshot_id!r}, current is {current_id!r}"
        )
    if current_id is not None:
        parent_metadata = validate_snapshot(
            inventory_paths, current_id, profile=profile
        )
        if parent_metadata.snapshot_id != expected_parent_snapshot_id:
            raise ValidationFailedError("current parent snapshot identity mismatch")

    publication_dir = run_paths.publication_dir()
    publication_dir.mkdir(parents=True, exist_ok=True)
    stage_parent = Path(tempfile.mkdtemp(prefix=".stage-", dir=publication_dir))
    try:
        staged_outcomes, staged_entries, outcome_count, entry_count = (
            _copy_committed_attempts(run_paths, run, stage_parent)
        )
        parent_accessions_dir, parent_sources_dir = _make_parent_input_dirs(
            stage_parent, inventory_paths, expected_parent_snapshot_id
        )
        try:
            anti_join_result = anti_join(
                StagingRelations(staged_outcomes, staged_entries, cohort_sources),
                parent_accessions_dir,
                parent_sources_dir,
                stage_parent / "anti-join",
                explicit_refresh=run.refresh_mode == "force",
                profile=profile,
            )
        except ValueError as exc:
            raise ValidationFailedError(str(exc)) from exc
        eligible_outcomes = [anti_join_result.new_accessions_path]
        if run.refresh_mode == "force":
            eligible_outcomes.append(anti_join_result.known_accessions_path)
        content_digest = canonical_hash(
            {
                "parent": expected_parent_snapshot_id,
                "outcomes": file_sha256(staged_outcomes),
                "entries": file_sha256(staged_entries),
                "cohort_accessions": file_sha256(cohort_accessions),
                "cohort_sources": file_sha256(cohort_sources),
                "snapshot_schema": SNAPSHOT_RELATION_VERSION,
                "entry_schema": ENTRY_SCHEMA_VERSION,
            }
        )
        snapshot_id = snapshot_id_for(expected_parent_snapshot_id, content_digest)
        staged_snapshot = stage_parent / snapshot_id
        connection = connect(profile)
        try:
            _create_merge_relations(
                connection,
                expected_parent_snapshot_id,
                inventory_paths,
                cohort_accessions,
                cohort_sources,
                staged_outcomes,
                staged_entries,
                eligible_outcomes,
                anti_join_result.candidate_entries_path,
                anti_join_result.new_sources_path,
                run.source_identity,
                run.refresh_mode == "force",
            )
            if (
                current_id is not None
                and not connection.execute(
                    "SELECT EXISTS (SELECT 1 FROM delta_accessions) OR "
                    "EXISTS (SELECT 1 FROM delta_sources)"
                ).fetchone()[0]
            ):
                with PublicationLock(inventory_paths):
                    actual = DAGCatalog(inventory_paths.snapshots_root).read_pointer(
                        branch_name
                    )
                    actual_tip = str(actual["snapshot_id"]) if actual else None
                    if actual_tip != expected_branch_tip:
                        raise StaleParentError(
                            f"expected branch tip {expected_branch_tip!r}, current is "
                            f"{actual_tip!r}"
                        )
                    return SnapshotPublication.no_op(parent_metadata)
            accession_query = (
                "SELECT accession, filing_cik, form, filing_date, report_date, bundle_url, "
                "bundle_size, index_url, index_sha256, first_indexed_by FROM delta_accessions "
                "ORDER BY form, filing_date, accession"
            )
            entry_query = (
                "SELECT entry_id, accession, table_kind, row_ordinal, sequence, document_type, "
                "document_label, description, filename, href, archive_url, byte_size "
                "FROM delta_entries JOIN delta_accessions USING(accession) "
                "ORDER BY form, filing_date, accession, row_ordinal, table_kind, entry_id"
            )
            source_query = (
                "SELECT accession, source_cik, first_seen_by FROM delta_sources "
                "ORDER BY source_cik, accession"
            )
            enumeration_query = (
                "SELECT accession, vehicle, source_url, payload_sha256 "
                "FROM delta_enumeration ORDER BY accession"
            )
            relation_queries = {
                INVENTORY_ACCESSIONS_SPEC.name: accession_query,
                INVENTORY_ENTRIES_SPEC.name: entry_query,
                INVENTORY_ACCESSION_SOURCES_SPEC.name: source_query,
                INVENTORY_ENUMERATION_SPEC.name: enumeration_query,
            }
            relation_records: dict[str, list[dict[str, Any]]] = {}
            for spec in INVENTORY_RELATIONS:
                rel = spec.name
                q = relation_queries[rel]
                key_col = spec.entity_key or spec.primary_key[0]
                part = _write_relation_part(
                    connection, staged_snapshot, snapshot_id, rel, q, key_col
                )
                relation_records[rel] = [part] if part else []
        finally:
            connection.close()

        # The catalog reconstructs relations from part rows, so a part-less
        # relation vanishes on read-back; omitting it here keeps the manifest
        # digest identical to its reconstruction.
        if not relation_records[INVENTORY_ENUMERATION_SPEC.name]:
            del relation_records[INVENTORY_ENUMERATION_SPEC.name]

        parent_refs: list[ParentRef] = []
        catalog = DAGCatalog(inventory_paths.snapshots_root)
        if expected_parent_snapshot_id:
            parent_node = catalog.get_manifest(expected_parent_snapshot_id)
            if parent_node is not None:
                parent_sha = (
                    catalog.get_manifest_sha256(expected_parent_snapshot_id) or ""
                )
                parent_refs.append(
                    ParentRef(
                        snapshot_id=expected_parent_snapshot_id,
                        manifest_sha256=parent_sha,
                    )
                )
                checkpoint_anchor_id = (
                    parent_node.checkpoint_anchor_id or expected_parent_snapshot_id
                )
                lineage_depth = parent_node.lineage_depth + 1
            else:
                checkpoint_anchor_id = expected_parent_snapshot_id
                lineage_depth = 1
        else:
            checkpoint_anchor_id = snapshot_id
            lineage_depth = 0

        dag_manifest = DAGNodeManifest(
            snapshot_id=snapshot_id,
            kind="delta" if expected_parent_snapshot_id else "checkpoint",
            parents=tuple(parent_refs),
            checkpoint_anchor_id=checkpoint_anchor_id,
            lineage_depth=lineage_depth,
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
            relations={
                rel: tuple(
                    PartDescriptor(
                        path=p["path"],
                        sha256=p["sha256"],
                        row_count=p["row_count"],
                        byte_size=p["byte_size"],
                        key_min=p.get("key_min"),
                        key_max=p.get("key_max"),
                    )
                    for p in parts
                )
                for rel, parts in relation_records.items()
            },
            logical_fingerprint=content_digest,
            schema_versions={
                "accessions": SNAPSHOT_RELATION_VERSION,
                "entries": str(ENTRY_SCHEMA_VERSION),
                "accession_enumeration": SNAPSHOT_RELATION_VERSION,
            },
            metadata={
                "run_intent_id": run.run_id,
                "parent_snapshot_id": expected_parent_snapshot_id or "",
                "base_snapshot_id": expected_parent_snapshot_id or "",
                "input_rows": {"outcomes": outcome_count, "entries": entry_count},
            },
        )
        staged_snapshot.mkdir(parents=True, exist_ok=True)
        metadata = validate_snapshot(
            inventory_paths,
            snapshot_id,
            manifest=dag_manifest,
            staged_root=staged_snapshot,
            profile=profile,
        )
        publish_node(
            inventory_paths.snapshots_root,
            dag_manifest,
            staged_dir=staged_snapshot,
            expected_parent_id=expected_branch_tip,
            branch_name=branch_name,
        )
        return SnapshotPublication.published(metadata)
    finally:
        shutil.rmtree(stage_parent, ignore_errors=True)
