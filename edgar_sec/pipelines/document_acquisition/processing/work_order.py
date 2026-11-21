from __future__ import annotations

import sqlite3

from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.infra.storage.duckdb import sql_identifier
from edgar_sec.pipelines.document_acquisition.arrow_schemas import (
    RESOLVED_OPERATION_SCHEMA,
)
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths
from edgar_sec.pipelines.document_acquisition.processing.models import (
    OperationRequest,
)
from edgar_sec.pipelines.document_acquisition.run_validation import (
    iter_resolved_work_order_operations,
)

_OPERATION_COLUMNS = tuple(RESOLVED_OPERATION_SCHEMA.names)
_TARGET_FINGERPRINT_KEYS = (
    "target_id accession form target_role target_type target_url "
    "source_origin lazy_index_trigger_id lazy_index_trigger_version"
).split()
OPERATION_PIN_KEYS = (
    "operation_id operation requested request_mode selected source_request_id "
    "input_ordinal input_role support_status capability_id capability_version "
    "handler_id handler_version output_kind"
).split()


def stream_resolved_operations(
    connection: sqlite3.Connection, paths: AcquisitionPaths, run_id: str
) -> None:
    columns = ", ".join(f"{sql_identifier(name)} TEXT" for name in _OPERATION_COLUMNS)
    connection.execute(f"CREATE TABLE resolved_operations ({columns})")
    insert = f"INSERT INTO resolved_operations VALUES ({', '.join('?' for _ in _OPERATION_COLUMNS)})"
    for row in iter_resolved_work_order_operations(paths, run_id):
        connection.execute(insert, tuple(row[name] for name in _OPERATION_COLUMNS))
    connection.execute(
        "CREATE INDEX resolved_operations_target ON resolved_operations (target_id, operation)"
    )
    connection.commit()


def resolved_operations(
    connection: sqlite3.Connection, target_id: str
) -> tuple[dict[str, object], ...]:
    rows = connection.execute(
        "SELECT * FROM resolved_operations WHERE target_id = ? ORDER BY operation",
        (target_id,),
    )
    return tuple(
        {
            **dict(row),
            "requested": bool(int(row["requested"])),
            "selected": bool(int(row["selected"])),
            "input_ordinal": (
                int(row["input_ordinal"]) if row["input_ordinal"] is not None else None
            ),
        }
        for row in rows
    )


def operation_requests(
    rows: tuple[dict[str, object], ...],
) -> tuple[OperationRequest, ...]:
    operations = []
    for row in rows:
        operation = str(row["operation"])
        source_request_id = row["source_request_id"]
        support_status = str(row["support_status"])
        requested = row["selected"] is True or (
            row["requested"] is True
            and (operation == "raw" or support_status == "unsupported")
        )
        pins = tuple(
            row[name]
            for name in (
                "capability_id",
                "capability_version",
                "handler_id",
                "handler_version",
                "output_kind",
            )
        )
        if support_status not in {"supported", "unsupported", "not_evaluated"}:
            raise ValueError("resolved operation support status is invalid")
        if support_status == "supported" and any(pin is None for pin in pins):
            raise ValueError("supported operation is missing immutable handler pins")
        if support_status != "supported" and any(pin is not None for pin in pins):
            raise ValueError("unresolved operation carries handler pins")
        if (
            requested
            and support_status == "supported"
            and (
                not isinstance(source_request_id, str)
                or row["input_role"] != "selected_target_body"
            )
        ):
            raise ValueError("requested operation has no resolved selected-body input")
        operations.append(
            OperationRequest(
                operation_id=str(row["operation_id"]),
                operation=operation,
                requested=requested,
                support_status=support_status,
                source_request_id=source_request_id,
                capability_id=pins[0],
                capability_version=pins[1],
                handler_id=pins[2],
                handler_version=pins[3],
                output_kind=pins[4],
            )
        )
    if len(operations) != 3 or sum(item.operation == "raw" for item in operations) != 1:
        raise ValueError("work-order operation coverage is invalid")
    return tuple(operations)


def request_fingerprint(
    target: dict[str, object], body, rows: tuple[dict[str, object], ...]
) -> str:
    return canonical_hash(
        {
            "target": {
                key: target[key] for key in _TARGET_FINGERPRINT_KEYS if key in target
            },
            "selected_body": {
                "sha256": body.sha256,
                "byte_size": body.byte_size,
                "source_response_sha256": body.source_response_sha256,
                "selected_filename": body.selected_filename,
            },
            "operations": [
                {key: row[key] for key in (*OPERATION_PIN_KEYS, "support_reason")}
                for row in rows
            ],
        }
    )
