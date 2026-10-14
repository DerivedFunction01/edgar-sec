from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pyarrow as pa

from edgar_sec.domain.document.path_facts import DocumentPathFacts
from edgar_sec.domain.document.route import document_route
from edgar_sec.engine.document_processing.acquisition_capabilities import (
    resolve_acquisition_capability,
)
from edgar_sec.foundation.runtime.settings.parquet import (
    resolve_parquet_read_batch_size,
)
from edgar_sec.infra.storage.duckdb import connect, sql_path_list
from edgar_sec.pipelines.document_acquisition.arrow_schemas import (
    RESOLVED_OPERATION_SCHEMA,
)
from edgar_sec.pipelines.document_acquisition.schemas import PLAN_RELATION_SCHEMAS

_OPERATIONS = {"raw", "render_to_txt", "render_to_xml"}
_DEFAULT_PRIORITY = {"render_to_xml": 0, "render_to_txt": 1}


def resolve_operation_group(
    target: dict[str, Any],
    operations: list[dict[str, Any]],
    source: dict[str, Any] | None,
    inputs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if (
        len(operations) != len(_OPERATIONS)
        or {operation["operation"] for operation in operations} != _OPERATIONS
    ):
        raise ValueError("target operation coverage is invalid")
    inputs_by_operation = {item["operation_id"]: item for item in inputs}
    if len(inputs_by_operation) != len(inputs):
        raise ValueError("operation input is duplicated")
    source_by_id = {source["source_request_id"]: source} if source else {}
    if any(item["source_request_id"] not in source_by_id for item in inputs):
        raise ValueError("operation input source reference is invalid")
    facts = DocumentPathFacts.from_archive_path(
        (source["canonical_path"] or "") if source is not None else ""
    )
    resolved = []
    for intent in operations:
        operation = intent["operation"]
        requested = intent["requested"]
        mode = intent["request_mode"]
        if operation not in _OPERATIONS:
            raise ValueError("operation is outside the S6 vocabulary")
        input_row = inputs_by_operation.pop(intent["operation_id"], None)
        source_id = input_row["source_request_id"] if input_row else None
        if not requested:
            support_status = "not_evaluated"
            support_reason = None
            pins = None
        else:
            pins = resolve_acquisition_capability(
                str(target["form"]),
                target["target_role"],
                operation,
                facts,
                document_route(facts.path_context),
            ).pins
            support_status = "supported" if pins is not None else "unsupported"
            support_reason = (
                None
                if pins is not None
                else "selected_body_input_unavailable"
                if source is None or not source["canonical_path"]
                else "capability_not_supported"
            )
        resolved.append(
            {
                "operation_id": intent["operation_id"],
                "target_id": intent["target_id"],
                "operation": operation,
                "requested": requested,
                "request_mode": mode,
                "selected": False,
                "source_request_id": source_id,
                "input_ordinal": input_row["input_ordinal"] if input_row else None,
                "input_role": input_row["input_role"] if input_row else None,
                "support_status": support_status,
                "support_reason": support_reason,
                "capability_id": pins[0] if pins else None,
                "capability_version": pins[1] if pins else None,
                "handler_id": pins[2] if pins else None,
                "handler_version": pins[3] if pins else None,
                "output_kind": pins[4] if pins else None,
            }
        )
    if inputs_by_operation:
        raise ValueError("operation input references an unknown operation")
    for row in resolved:
        if row["requested"] and row["support_status"] == "supported":
            row["selected"] = row["request_mode"] in {"mandatory_raw", "profile"}
    default_candidates = [
        row
        for row in resolved
        if row["requested"]
        and row["request_mode"] == "default_candidate"
        and row["support_status"] == "supported"
    ]
    if default_candidates:
        selected = min(
            default_candidates, key=lambda row: _DEFAULT_PRIORITY[row["operation"]]
        )
        selected["selected"] = True
    return sorted(resolved, key=lambda row: row["operation"])


def iter_resolved_operation_batches(
    targets: tuple[Path, ...],
    operations: tuple[Path, ...],
    sources: tuple[Path, ...],
    inputs: tuple[Path, ...],
) -> Iterator[pa.RecordBatch]:
    if not operations:
        return
    source_scan = (
        f"read_parquet({sql_path_list([str(path) for path in sources])})"
        if sources
        else _empty_scan("source_requests")
    )
    input_scan = (
        f"read_parquet({sql_path_list([str(path) for path in inputs])})"
        if inputs
        else _empty_scan("operation_inputs")
    )
    query = f"""SELECT t.target_id, t.form, t.target_role, t.target_type,
        o.operation_id, o.operation, o.requested, o.request_mode,
        s.source_request_id, s.canonical_path, i.input_ordinal, i.input_role
    FROM read_parquet({sql_path_list([str(path) for path in targets])}) t
    JOIN read_parquet({sql_path_list([str(path) for path in operations])}) o
        ON o.target_id = t.target_id
    LEFT JOIN {input_scan} i ON i.operation_id = o.operation_id
    LEFT JOIN {source_scan} s ON s.source_request_id = i.source_request_id
    ORDER BY t.target_id, o.operation"""
    with connect() as connection:
        reader = connection.execute(query).to_arrow_reader(
            resolve_parquet_read_batch_size()
        )
        group_target: dict[str, Any] | None = None
        group_operations: list[dict[str, Any]] = []
        group_source: dict[str, Any] | None = None
        group_inputs: list[dict[str, Any]] = []
        output_rows: list[dict[str, Any]] = []
        for batch in reader:
            for row in batch.to_pylist():
                target_id = row["target_id"]
                if group_target is not None and target_id != group_target["target_id"]:
                    output_rows.extend(
                        resolve_operation_group(
                            group_target,
                            group_operations,
                            group_source,
                            group_inputs,
                        )
                    )
                    if len(output_rows) >= resolve_parquet_read_batch_size():
                        table = pa.Table.from_pylist(
                            output_rows, schema=RESOLVED_OPERATION_SCHEMA
                        )
                        for output_batch in table.to_batches(
                            max_chunksize=resolve_parquet_read_batch_size()
                        ):
                            yield output_batch
                        output_rows = []
                    group_operations = []
                    group_source = None
                    group_inputs = []
                if group_target is None or target_id != group_target["target_id"]:
                    group_target = {
                        key: row[key]
                        for key in ("target_id", "form", "target_role", "target_type")
                    }
                operation = {
                    key: row[key]
                    for key in (
                        "operation_id",
                        "target_id",
                        "operation",
                        "requested",
                        "request_mode",
                    )
                }
                group_operations.append(operation)
                if row["source_request_id"] is not None:
                    group_source = {
                        "source_request_id": row["source_request_id"],
                        "canonical_path": row["canonical_path"],
                    }
                if row["input_ordinal"] is not None:
                    group_inputs.append(
                        {
                            "operation_id": operation["operation_id"],
                            "input_ordinal": row["input_ordinal"],
                            "source_request_id": row["source_request_id"],
                            "input_role": row["input_role"],
                        }
                    )
        if group_target is not None:
            output_rows.extend(
                resolve_operation_group(
                    group_target, group_operations, group_source, group_inputs
                )
            )
        if output_rows:
            table = pa.Table.from_pylist(output_rows, schema=RESOLVED_OPERATION_SCHEMA)
            for batch in table.to_batches(
                max_chunksize=resolve_parquet_read_batch_size()
            ):
                yield batch


def iter_resolved_operation_rows(
    relations: dict[str, tuple[Path, ...]],
) -> Iterator[dict[str, Any]]:
    operations = relations["resolved_operations"]
    if not operations:
        return
    sources = relations["source_requests"]
    source_scan = (
        f"read_parquet({sql_path_list([str(path) for path in sources])})"
        if sources
        else _empty_scan("source_requests")
    )
    targets = relations["targets"]
    query = f"""SELECT operation.*,
        target.form AS target_form, target.target_role AS target_role,
        target.target_type AS target_type, target.accession AS accession,
        target.filing_date AS filing_date,
        target.source_origin AS target_source_origin,
        target.retrieval_mode AS target_retrieval_mode,
        target.target_url AS target_url,
        source.target_id AS source_request_target_id,
        source.source_role AS source_request_role,
        source.source_origin AS source_request_origin,
        source.retrieval_mode AS source_request_retrieval_mode,
        source.request_url AS source_request_url,
        source.sequence AS source_request_sequence,
        source.canonical_path AS source_request_canonical_path
    FROM read_parquet({sql_path_list([str(path) for path in operations])}) operation
    JOIN read_parquet({sql_path_list([str(path) for path in targets])}) target
        ON target.target_id = operation.target_id
    LEFT JOIN {source_scan} source
        ON source.source_request_id = operation.source_request_id
    ORDER BY operation.target_id, operation.operation"""
    with connect() as connection:
        reader = connection.execute(query).to_arrow_reader(
            resolve_parquet_read_batch_size()
        )
        for batch in reader:
            yield from batch.to_pylist()


def _empty_scan(relation: str) -> str:
    types = {
        pa.string(): "VARCHAR",
        pa.bool_(): "BOOLEAN",
        pa.int32(): "INTEGER",
        pa.int64(): "BIGINT",
    }
    fields = PLAN_RELATION_SCHEMAS[relation]
    columns = ", ".join(
        f"CAST(NULL AS {types[field.type]}) AS {field.name}" for field in fields
    )
    return f"(SELECT {columns} WHERE FALSE)"


__all__ = [
    "iter_resolved_operation_batches",
    "iter_resolved_operation_rows",
    "resolve_operation_group",
]
