"""Validate target bundles and stream their work-order projection."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from edgar_sec.domain.forms.common.aliases import FORM_FAMILY_ALIASES
from edgar_sec.domain.forms.families.processing_profiles import (
    get_lazy_index_trigger,
    LAZY_INDEX_FORM_FAMILIES,
)
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.runtime.paths import part_file_name
from edgar_sec.foundation.runtime.settings.parquet import (
    resolve_parquet_read_batch_size,
)
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.infra.storage.duckdb import (
    connect,
    copy_query_to_parquet,
    sql_literal,
    sql_path_list,
)
from edgar_sec.infra.storage.parquet import StagedParquetWriter
from edgar_sec.pipelines.document_acquisition.arrow_schemas import (
    RESOLVED_OPERATION_SCHEMA,
    WORK_ORDER_SCHEMA,
)
from edgar_sec.pipelines.document_acquisition.plan_projection.operation_resolution import (
    iter_resolved_operation_batches,
)
from edgar_sec.pipelines.document_acquisition.plan_projection.target_contract import (
    _PLAN_BUNDLE_SCHEMA_VERSION,
    _TARGET_MATCHER_VERSION,
    _TARGET_SCHEMA_VERSION,
    TargetPlanError,
    WorkOrderProjection,
    _ValidatedPlan,
)
from edgar_sec.pipelines.document_acquisition.plan_projection.target_manifest import (
    _validate_manifest,
)
from edgar_sec.pipelines.document_acquisition.plan_projection.target_parts import (
    _validate_parts,
)
from edgar_sec.pipelines.document_acquisition.schemas import (
    OPERATION_INPUT_SCHEMA_VERSION,
    RESOLVED_OPERATION_SCHEMA_VERSION,
    SOURCE_REQUEST_SCHEMA_VERSION,
    TARGET_OPERATION_SCHEMA_VERSION,
)


def _validate_target_plan(plan_dir: Path) -> _ValidatedPlan:
    try:
        root, manifest = _validate_manifest(plan_dir)
        parts, relations = _validate_parts(root, manifest)
    except TargetPlanError:
        raise
    except (OSError, TypeError, ValueError) as error:
        raise TargetPlanError(f"target bundle is invalid: {error}") from error
    return _ValidatedPlan(root, manifest, parts, relations)


def _iter_projected_batches(parts: tuple[Path, ...], spool_path: Path):
    if not parts:
        return
    batch_size = resolve_parquet_read_batch_size()
    reason = (
        "CASE "
        "WHEN status = 'constructed_candidate' "
        "OR retrieval_mode = 'constructed_package' "
        "THEN 'candidate_not_authorized' "
        "WHEN status <> 'matched' THEN 'target_not_matched' "
        "WHEN retrieval_mode NOT IN ('direct_url', 'bundle_sequence', 'bundle_scan') "
        "THEN 'unsupported_retrieval_mode' ELSE NULL END"
    )
    form_triggers: dict[str, tuple[str, str]] = {}
    for family in sorted(LAZY_INDEX_FORM_FAMILIES):
        trigger = get_lazy_index_trigger(family)
        if trigger is None:
            continue
        for form in (family, *FORM_FAMILY_ALIASES.get(family, ())):
            form_triggers.setdefault(form, trigger)
    eligible_forms_sql = ", ".join(sql_literal(form) for form in sorted(form_triggers))
    trigger_id_sql = (
        "CASE form "
        + " ".join(
            f"WHEN {sql_literal(form)} THEN {sql_literal(trigger_id)}"
            for form, (trigger_id, _) in sorted(form_triggers.items())
        )
        + " ELSE NULL END"
    )
    trigger_version_sql = (
        "CASE form "
        + " ".join(
            f"WHEN {sql_literal(form)} THEN {sql_literal(version)}"
            for form, (_, version) in sorted(form_triggers.items())
        )
        + " ELSE NULL END"
    )
    trigger_predicate = (
        "catalog_direct_selection = 'exact_form_with_lazy_index' "
        "AND source_origin = 'catalog_direct' "
        "AND target_role = 'primary' "
        "AND retrieval_mode <> 'bundle_scan' "
        f"AND form IN ({eligible_forms_sql})"
    )
    query = (
        "SELECT target.*, ("
        f"{reason} IS NULL) AS executable, {reason} AS skip_reason "
        f", CASE WHEN {trigger_predicate} THEN ({trigger_id_sql}) "
        "ELSE NULL END AS lazy_index_trigger_id, "
        f"CASE WHEN {trigger_predicate} THEN ({trigger_version_sql}) "
        "ELSE NULL END AS lazy_index_trigger_version "
        f"FROM read_parquet({sql_path_list([str(path) for path in parts])}, hive_partitioning=false) AS target "
        "ORDER BY form, accession, request_id, "
        "COALESCE(inventory_entry_id, ''), status"
    )
    # The ORDER BY is materialized through the COPY sink, whose rows are in
    # sort order; a streamed reader may emit parallel sort runs concatenated.
    with connect() as con:
        copy_query_to_parquet(con, query, spool_path, schema=WORK_ORDER_SCHEMA)
    yield from pq.ParquetFile(spool_path).iter_batches(batch_size=batch_size)


def load_acquisition_work_order(
    plan_dir: str | os.PathLike[str],
    parquet_path: str | os.PathLike[str],
) -> WorkOrderProjection:
    """Validate an entire bundle, then atomically stream its work-order rows."""
    validated = _validate_target_plan(Path(plan_dir))
    destination = Path(parquet_path).resolve()
    if destination == validated.root or destination.is_relative_to(validated.root):
        raise TargetPlanError(
            "work-order output must not modify the immutable target bundle"
        )
    if os.path.lexists(destination):
        raise TargetPlanError("work-order output already exists")
    manifest = validated.manifest
    executable_count = skipped_count = 0
    writer = StagedParquetWriter(destination, WORK_ORDER_SCHEMA)
    relation_parts: dict[str, list[dict[str, Any]]] = {
        "targets": [],
        **{name: [] for name in validated.relations},
        "resolved_operations": [],
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    spool = tempfile.TemporaryDirectory(
        dir=destination.parent, prefix=".work-order-spool-"
    )
    try:
        for batch in _iter_projected_batches(
            validated.parts, Path(spool.name) / "targets.parquet"
        ):
            batch_executable_count = int(
                pc.sum(
                    pc.cast(
                        batch.column(batch.schema.get_field_index("executable")),
                        pa.int64(),
                    )
                ).as_py()
            )
            executable_count += batch_executable_count
            skipped_count += batch.num_rows - batch_executable_count
            writer.write_batch(batch)
        writer.commit(expected_count=manifest["target_row_count"])
        relation_parts["targets"].append(
            {
                "path": destination.name,
                "row_count": manifest["target_row_count"],
                "byte_size": destination.stat().st_size,
                "sha256": file_sha256(destination),
            }
        )
        for relation, paths in validated.relations.items():
            for source in paths:
                original = source.relative_to(validated.root)
                output = destination.parent / original
                output.parent.mkdir(parents=True, exist_ok=True)
                if output.exists() or output.is_symlink():
                    raise TargetPlanError("work-order relation output already exists")
                shutil.copyfile(source, output)
                relation_parts[relation].append(
                    {
                        "path": original.as_posix(),
                        "row_count": pq.ParquetFile(source).metadata.num_rows,
                        "byte_size": output.stat().st_size,
                        "sha256": file_sha256(output),
                    }
                )
        resolved_path = destination.parent / "resolved_operations" / part_file_name(0)
        resolved_writer = StagedParquetWriter(resolved_path, RESOLVED_OPERATION_SCHEMA)
        try:
            for batch in iter_resolved_operation_batches(
                validated.parts,
                validated.relations["target_operations"],
                validated.relations["source_requests"],
                validated.relations["operation_inputs"],
                spool_dir=Path(spool.name),
            ):
                resolved_writer.write_batch(batch)
            resolved_writer.commit(
                expected_count=manifest["relation_row_counts"]["target_operations"]
            )
        except Exception:
            resolved_writer.reset()
            resolved_path.unlink(missing_ok=True)
            raise
        relation_parts["resolved_operations"].append(
            {
                "path": f"resolved_operations/{part_file_name(0)}",
                "row_count": manifest["relation_row_counts"]["target_operations"],
                "byte_size": resolved_path.stat().st_size,
                "sha256": file_sha256(resolved_path),
            }
        )
    except Exception:
        writer.reset()
        destination.unlink(missing_ok=True)
        for relation, descriptors in relation_parts.items():
            if relation == "targets":
                continue
            for descriptor in descriptors:
                (destination.parent / descriptor["path"]).unlink(missing_ok=True)
        raise
    finally:
        spool.cleanup()
    relation_counts = {
        relation: sum(part["row_count"] for part in descriptors)
        for relation, descriptors in relation_parts.items()
    }
    relation_digests = {
        relation: canonical_hash(
            [
                [
                    f"work_order/{part['path']}",
                    part["row_count"],
                    part["byte_size"],
                    part["sha256"],
                ]
                for part in descriptors
            ]
        )
        for relation, descriptors in relation_parts.items()
    }
    return WorkOrderProjection(
        plan_id=manifest["plan_id"],
        plan_digest=manifest["plan_digest"],
        bundle_schema_version=_PLAN_BUNDLE_SCHEMA_VERSION,
        matcher_version=_TARGET_MATCHER_VERSION,
        target_schema_version=_TARGET_SCHEMA_VERSION,
        target_operation_schema_version=TARGET_OPERATION_SCHEMA_VERSION,
        source_request_schema_version=SOURCE_REQUEST_SCHEMA_VERSION,
        operation_input_schema_version=OPERATION_INPUT_SCHEMA_VERSION,
        resolved_operation_schema_version=RESOLVED_OPERATION_SCHEMA_VERSION,
        catalog_plan_id=manifest["catalog_plan_id"],
        catalog_plan_digest=manifest["catalog_plan_digest"],
        inventory_snapshot_id=manifest["inventory_snapshot_id"],
        inventory_snapshot_digest=manifest["inventory_snapshot_digest"],
        target_row_count=manifest["target_row_count"],
        executable_count=int(executable_count),
        skipped_count=int(skipped_count),
        parquet_path=destination,
        relation_parts=relation_parts,
        relation_counts=relation_counts,
        relation_digests=relation_digests,
    )


__all__ = ["load_acquisition_work_order"]
