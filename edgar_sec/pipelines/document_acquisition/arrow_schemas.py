"""Arrow schemas for persisted document-acquisition relations."""

from __future__ import annotations

import pyarrow as pa

from edgar_sec.pipelines.document_acquisition.schemas import target_relation_schema

_TARGET_SCHEMA = target_relation_schema()

WORK_ORDER_SCHEMA = pa.schema(
    [
        *_TARGET_SCHEMA,
        pa.field("executable", pa.bool_(), nullable=False),
        pa.field("skip_reason", pa.string(), nullable=True),
    ],
    metadata=_TARGET_SCHEMA.metadata,
)

__all__ = ["WORK_ORDER_SCHEMA"]
