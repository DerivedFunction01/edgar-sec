from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.serialization import canonical_hash, canonical_json
from edgar_sec.foundation.runtime.settings.parquet import DEFAULT_ROW_GROUP_SIZE
from edgar_sec.pipelines.document_planning.paths import (
    form_partition_directory,
    plan_target_part_path,
)
from edgar_sec.pipelines.document_planning.schemas import (
    OPERATION_INPUT_SCHEMA_VERSION,
    PLAN_BUNDLE_SCHEMA_VERSION,
    PLAN_RELATION_SCHEMAS,
    PROFILE_SCHEMA_VERSION,
    SOURCE_REQUEST_SCHEMA_VERSION,
    TARGET_OPERATION_SCHEMA_VERSION,
    TARGET_SCHEMA_VERSION,
)

_OPERATIONS = ("raw", "render_to_txt", "render_to_xml")


def write_plan_bundle(
    plan_root: Path,
    plan_id: str,
    identity: dict[str, Any],
    targets: list[dict[str, Any]],
) -> dict[str, Any]:
    relation_rows: dict[str, list[dict[str, Any]]] = {
        name: [] for name in PLAN_RELATION_SCHEMAS
    }
    for target in targets:
        form = target["form"]
        matched = target["status"] == "matched"
        source_id = None
        if matched:
            canonical_path = target["target_url"].rsplit("/", 1)[-1]
            source = {
                "source_request_id": "",
                "target_id": target["target_id"],
                "source_role": "primary_body",
                "source_origin": target["source_origin"],
                "retrieval_mode": target["retrieval_mode"],
                "request_url": target["target_url"],
                "sequence": target["sequence"],
                "canonical_path": canonical_path,
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
            source["source_request_id"] = source_id
            relation_rows["source_requests"].append({"form": form, **source})
        for operation in _OPERATIONS:
            requested = operation == "raw"
            request_mode = "mandatory_raw" if requested else "not_requested"
            operation_id = canonical_hash([target["target_id"], operation])
            relation_rows["target_operations"].append(
                {
                    "form": form,
                    "operation_id": operation_id,
                    "target_id": target["target_id"],
                    "operation": operation,
                    "requested": requested,
                    "request_mode": request_mode,
                }
            )
            if matched and requested:
                relation_rows["operation_inputs"].append(
                    {
                        "form": form,
                        "operation_id": operation_id,
                        "input_ordinal": 0,
                        "source_request_id": source_id,
                        "input_role": "selected_target_body",
                    }
                )
    parts = []
    relation_counts = {}
    requested_operation_counts = Counter()
    for relation, schema in PLAN_RELATION_SCHEMAS.items():
        rows = (
            relation_rows[relation]
            if relation != "targets"
            else [{"form": row["form"], **row} for row in targets]
        )
        relation_counts[relation] = len(rows)
        for row in rows:
            if relation == "target_operations" and row["requested"]:
                requested_operation_counts[row["operation"]] += 1
        by_form: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_form.setdefault(row["form"], []).append(row)
        for form, form_rows in sorted(by_form.items()):
            sort_key = {
                "target_operations": lambda row: (row["target_id"], row["operation"]),
                "source_requests": lambda row: row["source_request_id"],
                "operation_inputs": lambda row: (
                    row["operation_id"],
                    row["input_ordinal"],
                ),
            }.get(relation)
            if sort_key is not None:
                form_rows.sort(key=sort_key)
            if relation == "targets":
                relative = plan_target_part_path(form, 0)
            else:
                relative = (
                    f"{relation}/{form_partition_directory(form)}/part-00000.parquet"
                )
            path = plan_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            values = [{name: row[name] for name in schema.names} for row in form_rows]
            pq.write_table(
                pa.Table.from_pylist(values, schema=schema),
                path,
                row_group_size=DEFAULT_ROW_GROUP_SIZE,
            )
            parts.append(
                {
                    "relation": relation,
                    "path": relative,
                    "form": form,
                    "rows": len(values),
                    "byte_size": path.stat().st_size,
                    "sha256": file_sha256(path),
                }
            )
    parts.sort(key=lambda part: (part["relation"], part["form"], part["path"]))
    statuses = Counter(row["status"] for row in targets)
    origins = Counter(row["source_origin"] for row in targets)
    manifest = {
        "plan_id": plan_id,
        "bundle_schema_version": PLAN_BUNDLE_SCHEMA_VERSION,
        "target_schema_version": TARGET_SCHEMA_VERSION,
        "target_operation_schema_version": TARGET_OPERATION_SCHEMA_VERSION,
        "source_request_schema_version": SOURCE_REQUEST_SCHEMA_VERSION,
        "operation_input_schema_version": OPERATION_INPUT_SCHEMA_VERSION,
        "matcher_version": identity["matcher_version"],
        "row_group_size": DEFAULT_ROW_GROUP_SIZE,
        "profile_id": "profile-fixture",
        "profile_schema_version": PROFILE_SCHEMA_VERSION,
        "profile_version": "1",
        "profile_digest": identity["profile_digest"],
        "catalog_plan_id": identity["catalog_plan_id"],
        "catalog_plan_digest": identity["catalog_plan_digest"],
        "inventory_snapshot_id": identity["inventory_snapshot_id"],
        "inventory_snapshot_digest": identity["inventory_snapshot_digest"],
        "plan_identity": identity,
        "target_row_count": len(targets),
        "status_counts": dict(statuses),
        "origin_counts": dict(origins),
        "reason_counts": {},
        "relation_row_counts": relation_counts,
        "requested_operation_counts": dict(requested_operation_counts),
        "default_candidate_operation_counts": {},
        "unrequested_operation_counts": {
            "render_to_txt": len(targets),
            "render_to_xml": len(targets),
        },
        "unique_source_request_count": len(relation_rows["source_requests"]),
        "parts": parts,
    }
    manifest["plan_digest"] = canonical_hash(manifest)
    (plan_root / "plan.json").write_text(canonical_json(manifest), encoding="utf-8")
    return manifest
