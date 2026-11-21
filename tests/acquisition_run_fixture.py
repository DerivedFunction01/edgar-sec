from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.pipelines.document_acquisition.arrow_schemas import (
    RESOLVED_OPERATION_SCHEMA,
)
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.pipelines.document_acquisition.plan_projection.operation_resolution import (
    resolve_operation_group,
)
from edgar_sec.pipelines.document_acquisition.run_state.models import (
    WorkOrderOperationSeed,
    WorkOrderTargetSeed,
)
from edgar_sec.pipelines.document_acquisition.run_state.store import (
    SCHEMA_VERSION as RUN_STATE_SCHEMA_VERSION,
    initialize_run_state,
)
from edgar_sec.pipelines.document_acquisition.schemas import (
    ACQUISITION_CONTRACT_VERSION,
    RUN_SCHEMA_VERSION,
    RESOLVED_OPERATION_SCHEMA_VERSION,
    WORK_ORDER_SCHEMA_VERSION,
)
from edgar_sec.pipelines.document_planning.schemas import (
    MATCHER_VERSION,
    OPERATION_INPUT_SCHEMA_VERSION,
    PLAN_BUNDLE_SCHEMA_VERSION,
    PLAN_RELATION_SCHEMAS,
    SOURCE_REQUEST_SCHEMA_VERSION,
    TARGET_OPERATION_SCHEMA_VERSION,
    TARGET_SCHEMA,
    TARGET_SCHEMA_VERSION,
)

_ACCESSION = "0000320193-20-000096"
_ACCESSION_COMPACT = _ACCESSION.replace("-", "")


def make_acquisition_run(
    artifacts_root: Path,
    *,
    lazy: bool = True,
    bundle: bool = False,
    executable: bool = True,
    sibling_failure: bool = False,
    default_candidates: bool = False,
    form: str = "10-K",
    filename: str | None = None,
):
    paths = resolve_acquisition_paths(artifacts_root=artifacts_root)
    run_id = "acq_test-run"
    run_root = paths.run_dir(run_id)
    work_order_root = paths.work_order_root(run_id)
    work_order_root.mkdir(parents=True)
    archive_root = (
        f"https://www.sec.gov/Archives/edgar/data/320193/{_ACCESSION_COMPACT}/"
    )
    if filename is not None:
        target_url = f"{archive_root}{filename}"
    elif bundle or default_candidates:
        target_url = f"{archive_root}{_ACCESSION}.txt"
    else:
        target_url = f"{archive_root}cover.htm"
    row = {
        "target_id": "target-1",
        "accession": _ACCESSION,
        "form": form,
        "filing_date": "2020-01-30",
        "request_id": "request-1",
        "target_role": "primary",
        "target_type": "primary",
        "optional": False,
        "inventory_entry_id": None,
        "status": "matched",
        "status_reason": None,
        "source_origin": "catalog_direct" if lazy else "inventory_index",
        "retrieval_mode": "bundle_sequence" if bundle else "direct_url",
        "target_url": target_url,
        "sequence": 2 if bundle else 1,
        "byte_size": None,
        "availability_evidence": "catalog_direct" if lazy else "index_row",
        "catalog_direct_selection": (
            "exact_form_with_lazy_index" if lazy else "submitted_primary"
        ),
        "executable": executable,
        "skip_reason": None if executable else "target_not_matched",
        "lazy_index_trigger_id": "test.lazy-index" if lazy else None,
        "lazy_index_trigger_version": "1" if lazy else None,
    }
    work_order_schema = pa.schema(
        [
            *TARGET_SCHEMA,
            pa.field("executable", pa.bool_(), nullable=False),
            pa.field("skip_reason", pa.string(), nullable=True),
            pa.field("lazy_index_trigger_id", pa.string()),
            pa.field("lazy_index_trigger_version", pa.string()),
        ],
        metadata=TARGET_SCHEMA.metadata,
    )
    rows = [row]
    if sibling_failure:
        sibling = dict(row)
        sibling.update(
            target_id="target-2",
            request_id="request-2",
            target_url=target_url.rsplit("/", 1)[0] + "/sibling.htm",
            catalog_direct_selection="submitted_primary",
            lazy_index_trigger_id=None,
            lazy_index_trigger_version=None,
        )
        rows.append(sibling)
    work_order_path = work_order_root / "part-00000.parquet"
    pq.write_table(
        pa.Table.from_pylist(rows, schema=work_order_schema), work_order_path
    )
    source_rows = []
    operation_rows = []
    input_rows = []
    for target in rows:
        source = {
            "target_id": target["target_id"],
            "source_role": "primary_body",
            "source_origin": target["source_origin"],
            "retrieval_mode": target["retrieval_mode"],
            "request_url": target["target_url"],
            "sequence": target["sequence"],
            "canonical_path": target["target_url"].rsplit("/", 1)[-1],
        }
        source_id = canonical_hash(
            [
                source["target_id"],
                source["source_role"],
                source["source_origin"],
                source["retrieval_mode"],
                source["request_url"],
                source["sequence"],
                source["canonical_path"],
            ]
        )
        source_rows.append({"source_request_id": source_id, **source})
        for operation in ("raw", "render_to_txt", "render_to_xml"):
            requested = operation == "raw" or default_candidates
            request_mode = (
                "mandatory_raw"
                if operation == "raw"
                else "default_candidate"
                if requested
                else "not_requested"
            )
            operation_id = canonical_hash([target["target_id"], operation])
            operation_rows.append(
                {
                    "operation_id": operation_id,
                    "target_id": target["target_id"],
                    "operation": operation,
                    "requested": requested,
                    "request_mode": request_mode,
                }
            )
            if requested:
                input_rows.append(
                    {
                        "operation_id": operation_id,
                        "input_ordinal": 0,
                        "source_request_id": source_id,
                        "input_role": "selected_target_body",
                    }
                )
    resolved_rows = []
    for target in rows:
        target_intents = [
            operation
            for operation in operation_rows
            if operation["target_id"] == target["target_id"]
        ]
        target_operation_ids = {
            operation["operation_id"] for operation in target_intents
        }
        resolved_rows.extend(
            resolve_operation_group(
                {
                    "target_id": target["target_id"],
                    "form": target["form"],
                    "target_role": target["target_role"],
                    "target_type": target["target_type"],
                },
                target_intents,
                next(
                    source
                    for source in source_rows
                    if source["target_id"] == target["target_id"]
                ),
                [
                    item
                    for item in input_rows
                    if item["operation_id"] in target_operation_ids
                ],
            )
        )
    operation_seeds = [WorkOrderOperationSeed(**row) for row in resolved_rows]
    relation_parts = {
        "targets": [
            {
                "path": "work_order/part-00000.parquet",
                "row_count": len(rows),
                "byte_size": work_order_path.stat().st_size,
                "sha256": file_sha256(work_order_path),
            }
        ]
    }
    relation_rows = {
        "target_operations": operation_rows,
        "source_requests": source_rows,
        "operation_inputs": input_rows,
    }
    for relation, values in relation_rows.items():
        values.sort(
            key=(
                (lambda item: (item["target_id"], item["operation"]))
                if relation == "target_operations"
                else (lambda item: item["source_request_id"])
                if relation == "source_requests"
                else (lambda item: (item["operation_id"], item["input_ordinal"]))
            )
        )
        relation_path = work_order_root / relation / "form=10-K" / "part-00000.parquet"
        relation_path.parent.mkdir(parents=True)
        pq.write_table(
            pa.Table.from_pylist(values, schema=PLAN_RELATION_SCHEMAS[relation]),
            relation_path,
        )
        relative = relation_path.relative_to(run_root).as_posix()
        relation_parts[relation] = [
            {
                "path": relative,
                "row_count": len(values),
                "byte_size": relation_path.stat().st_size,
                "sha256": file_sha256(relation_path),
            }
        ]
    resolved_path = work_order_root / "resolved_operations" / "part-00000.parquet"
    resolved_path.parent.mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pylist(resolved_rows, schema=RESOLVED_OPERATION_SCHEMA),
        resolved_path,
    )
    relation_parts["resolved_operations"] = [
        {
            "path": resolved_path.relative_to(run_root).as_posix(),
            "row_count": len(resolved_rows),
            "byte_size": resolved_path.stat().st_size,
            "sha256": file_sha256(resolved_path),
        }
    ]
    work_order_relations = {
        relation: {
            "row_count": sum(part["row_count"] for part in parts),
            "sha256": canonical_hash(
                [
                    [
                        part["path"],
                        part["row_count"],
                        part["byte_size"],
                        part["sha256"],
                    ]
                    for part in parts
                ]
            ),
            "parts": parts,
        }
        for relation, parts in relation_parts.items()
    }
    initialize_run_state(
        paths.run_state_path(run_id),
        [
            WorkOrderTargetSeed(target["target_id"], executable, target["skip_reason"])
            for target in rows
        ],
        operation_seeds,
    )
    manifest = {
        "run_id": run_id,
        "run_schema_version": RUN_SCHEMA_VERSION,
        "acquisition_contract_version": ACQUISITION_CONTRACT_VERSION,
        "target_plan_id": "plan-1",
        "target_plan_digest": "a" * 64,
        "bundle_schema_version": PLAN_BUNDLE_SCHEMA_VERSION,
        "target_schema_version": TARGET_SCHEMA_VERSION,
        "target_operation_schema_version": TARGET_OPERATION_SCHEMA_VERSION,
        "source_request_schema_version": SOURCE_REQUEST_SCHEMA_VERSION,
        "operation_input_schema_version": OPERATION_INPUT_SCHEMA_VERSION,
        "resolved_operation_schema_version": RESOLVED_OPERATION_SCHEMA_VERSION,
        "matcher_version": MATCHER_VERSION,
        "catalog_plan_id": "catalog-1",
        "catalog_plan_digest": "b" * 64,
        "inventory_snapshot_id": None,
        "inventory_snapshot_digest": None,
        "work_order_schema_version": WORK_ORDER_SCHEMA_VERSION,
        "work_order_relations": work_order_relations,
        "work_order_parts": relation_parts["targets"],
        "target_row_count": len(rows),
        "executable_count": len(rows) * int(executable),
        "skipped_count": len(rows) * int(not executable),
        "run_state_schema_version": RUN_STATE_SCHEMA_VERSION,
    }
    manifest["run_digest"] = canonical_hash(manifest)
    atomic_write_json(paths.run_manifest_path(run_id), manifest)
    return paths, run_id, row


__all__ = ["make_acquisition_run"]
