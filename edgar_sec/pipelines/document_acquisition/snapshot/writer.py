"""Publish completed acquisition runs to immutable DAG snapshot relations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.runtime.paths import validate_safe_id
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.manifest import (
    DAGNodeManifest,
    ParentRef,
    PartDescriptor,
)
from edgar_sec.infra.storage.dag.working.publication import (
    StaleParentError,
    publish_node,
)
from edgar_sec.infra.storage.parquet import (
    DEFAULT_COMPRESSION,
    read_parquet_key_bounds,
    write_parquet_table,
)
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths
from edgar_sec.pipelines.document_acquisition.run_validation import (
    iter_work_order_rows,
    load_validated_work_order,
)

from .errors import RunNotPublishableError
from .loading import _load_run_db, _validate_run_terminality
from .models import (
    PUBLICATION_RECEIPT_SCHEMA_VERSION,
    PublicationReceipt,
    SnapshotPublication,
)
from .receipt import _write_receipt, read_publication_receipt
from .schema import SNAPSHOT_SCHEMA_VERSION
from .specs import ACQUISITION_RELATIONS_BY_NAME
from .tables import _assemble_snapshot_tables, _validate_referential_integrity

__all__ = ["publish_acquisition_run"]


def publish_acquisition_run(
    paths: AcquisitionPaths,
    run_id: str,
    *,
    branch_name: str = "main",
    expected_branch_tip: str | None = None,
    allow_errors: bool = False,
) -> SnapshotPublication:
    validate_safe_id(run_id, "run_id")
    prior = read_publication_receipt(paths, run_id)
    if prior is not None:
        return SnapshotPublication.already_published(run_id, prior.snapshot_id)

    manifest_path = paths.run_manifest_path(run_id)
    if not manifest_path.is_file():
        raise RunNotPublishableError(f"run manifest is missing: {run_id}")

    db_data = _load_run_db(paths.run_state_path(run_id))
    work_order_parts = load_validated_work_order(paths, run_id)
    work_targets = list(iter_work_order_rows(work_order_parts))
    _validate_run_terminality(work_targets, db_data, allow_errors)

    catalog = DAGCatalog(paths.snapshots_root)
    pointer = catalog.read_pointer(branch_name)
    current_tip = str(pointer["snapshot_id"]) if pointer else None
    if expected_branch_tip is not None and expected_branch_tip != current_tip:
        raise StaleParentError(
            f"branch {branch_name} tip is {current_tip!r}, expected {expected_branch_tip!r}"
        )

    tables = _assemble_snapshot_tables(paths, run_id, work_targets, db_data)
    _validate_referential_integrity(tables)

    stage_id = f"{run_id}_{uuid.uuid4().hex[:8]}"
    staged_dir = paths.snapshots_root / f".stage-{stage_id}"
    staged_dir.mkdir(parents=True, exist_ok=True)

    try:
        part_descriptors: dict[str, tuple[PartDescriptor, ...]] = {}
        row_counts: dict[str, int] = {}
        for name, table in tables.items():
            spec = ACQUISITION_RELATIONS_BY_NAME[name]
            rel_dir = staged_dir / name
            rel_dir.mkdir(parents=True, exist_ok=True)
            part_path = rel_dir / "part-00000.parquet"
            write_parquet_table(
                table,
                part_path,
                compression=DEFAULT_COMPRESSION,
            )
            key_min, key_max = None, None
            if table.num_rows > 0:
                key_min, key_max = read_parquet_key_bounds(
                    part_path, spec.primary_key[0]
                )
            part_sha = file_sha256(part_path)
            descriptor = PartDescriptor(
                path=f"{name}/part-00000.parquet",
                sha256=part_sha,
                row_count=table.num_rows,
                byte_size=part_path.stat().st_size,
                key_min=key_min,
                key_max=key_max,
            )
            part_descriptors[name] = (descriptor,)
            row_counts[name] = table.num_rows

        all_part_hashes = sorted(
            desc.sha256 for parts in part_descriptors.values() for desc in parts
        )
        snapshot_id = (
            f"snap_{canonical_hash([run_id, current_tip or '', all_part_hashes])[:32]}"
        )
        created_at_utc = datetime.now(UTC).isoformat()

        parent_manifest = catalog.get_manifest(current_tip) if current_tip else None
        parents = (
            (ParentRef(current_tip, parent_manifest.logical_fingerprint),)
            if current_tip and parent_manifest
            else ()
        )
        checkpoint_anchor = (
            parent_manifest.checkpoint_anchor_id if parent_manifest else snapshot_id
        )
        depth = (parent_manifest.lineage_depth + 1) if parent_manifest else 0
        node_kind = "delta" if parents else "checkpoint"

        manifest = DAGNodeManifest(
            snapshot_id=snapshot_id,
            kind=node_kind,
            parents=parents,
            checkpoint_anchor_id=checkpoint_anchor,
            lineage_depth=depth,
            created_at=created_at_utc,
            relations=part_descriptors,
            logical_fingerprint=canonical_hash(all_part_hashes),
            schema_versions={"snapshot_schema_version": str(SNAPSHOT_SCHEMA_VERSION)},
            metadata={"run_id": run_id},
        )

        publish_node(
            paths.snapshots_root,
            manifest,
            staged_dir=staged_dir,
            expected_parent_id=current_tip,
            branch_name=branch_name,
        )

        receipt = PublicationReceipt(
            receipt_schema_version=PUBLICATION_RECEIPT_SCHEMA_VERSION,
            snapshot_id=snapshot_id,
            run_id=run_id,
            branch=branch_name,
            published_at_utc=created_at_utc,
            adopted_payload_count=row_counts.get("payload_index", 0),
            adopted_payload_bytes=sum(
                tables["payload_index"].column("byte_size").to_pylist()
            )
            if row_counts.get("payload_index", 0) > 0
            else 0,
            relation_row_counts=row_counts,
        )
        _write_receipt(paths, run_id, receipt)
        return SnapshotPublication.published(run_id, snapshot_id, receipt)
    finally:
        if staged_dir.exists():
            import shutil

            shutil.rmtree(staged_dir, ignore_errors=True)
