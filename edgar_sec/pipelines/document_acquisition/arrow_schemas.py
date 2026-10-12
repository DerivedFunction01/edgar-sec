"""Arrow schemas for persisted document-acquisition relations."""

from __future__ import annotations

import pyarrow as pa

from edgar_sec.pipelines.document_acquisition.schemas import (
    PLAN_RELATION_SCHEMAS,
    target_relation_schema,
)

_TARGET_SCHEMA = target_relation_schema()

WORK_ORDER_SCHEMA = pa.schema(
    [
        *_TARGET_SCHEMA,
        pa.field("executable", pa.bool_(), nullable=False),
        pa.field("skip_reason", pa.string(), nullable=True),
        pa.field("lazy_index_trigger_id", pa.string()),
        pa.field("lazy_index_trigger_version", pa.string()),
    ],
    metadata=_TARGET_SCHEMA.metadata,
)

RESOLVED_OPERATION_SCHEMA = pa.schema(
    [
        pa.field("operation_id", pa.string(), nullable=False),
        pa.field("target_id", pa.string(), nullable=False),
        pa.field("operation", pa.string(), nullable=False),
        pa.field("requested", pa.bool_(), nullable=False),
        pa.field("request_mode", pa.string(), nullable=False),
        pa.field("selected", pa.bool_(), nullable=False),
        pa.field("source_request_id", pa.string()),
        pa.field("input_ordinal", pa.int32()),
        pa.field("input_role", pa.string()),
        pa.field("support_status", pa.string(), nullable=False),
        pa.field("support_reason", pa.string()),
        pa.field("capability_id", pa.string()),
        pa.field("capability_version", pa.string()),
        pa.field("handler_id", pa.string()),
        pa.field("handler_version", pa.string()),
        pa.field("output_kind", pa.string()),
    ]
)

WORK_ORDER_RELATION_SCHEMAS = {
    "targets": WORK_ORDER_SCHEMA,
    **{
        name: schema
        for name, schema in PLAN_RELATION_SCHEMAS.items()
        if name != "targets"
    },
    "resolved_operations": RESOLVED_OPERATION_SCHEMA,
}

__all__ = [
    "RESOLVED_OPERATION_SCHEMA",
    "WORK_ORDER_RELATION_SCHEMAS",
    "WORK_ORDER_SCHEMA",
]
