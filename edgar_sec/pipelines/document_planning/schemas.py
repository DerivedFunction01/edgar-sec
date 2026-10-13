"""Target relation schema and document-planning format versions."""

from __future__ import annotations

import pyarrow as pa

from edgar_sec.domain.filing_catalog.schemas import TARGET_PLAN_SCHEMA_VERSION
from edgar_sec.pipelines.document_inventory.schemas import INVENTORY_RELATIONS

TARGET_SCHEMA_VERSION = 1
TARGET_OPERATION_SCHEMA_VERSION = 1
SOURCE_REQUEST_SCHEMA_VERSION = 1
OPERATION_INPUT_SCHEMA_VERSION = 1
PLAN_BUNDLE_SCHEMA_VERSION = 4
MATCHER_VERSION = "target-matcher-v4"
PROFILE_SCHEMA_VERSION = "1"

TARGET_COLUMNS = (
    "target_id",
    "accession",
    "form",
    "filing_date",
    "request_id",
    "target_role",
    "target_type",
    "optional",
    "inventory_entry_id",
    "status",
    "status_reason",
    "source_origin",
    "retrieval_mode",
    "target_url",
    "sequence",
    "byte_size",
    "availability_evidence",
    "catalog_direct_selection",
)

TARGET_SCHEMA = pa.schema(
    [
        pa.field("target_id", pa.string(), nullable=False),
        pa.field("accession", pa.string(), nullable=False),
        pa.field("form", pa.string(), nullable=False),
        pa.field("filing_date", pa.string(), nullable=False),
        pa.field("request_id", pa.string(), nullable=False),
        pa.field("target_role", pa.string(), nullable=False),
        pa.field("target_type", pa.string(), nullable=False),
        pa.field("optional", pa.bool_(), nullable=False),
        pa.field("inventory_entry_id", pa.string(), nullable=True),
        pa.field("status", pa.string(), nullable=False),
        pa.field("status_reason", pa.string(), nullable=True),
        pa.field("source_origin", pa.string(), nullable=False),
        pa.field("retrieval_mode", pa.string(), nullable=False),
        pa.field("target_url", pa.string(), nullable=True),
        pa.field("sequence", pa.int32(), nullable=True),
        pa.field("byte_size", pa.int64(), nullable=True),
        pa.field("availability_evidence", pa.string(), nullable=False),
        pa.field("catalog_direct_selection", pa.string(), nullable=True),
    ]
)

TARGET_OPERATION_SCHEMA = pa.schema(
    [
        pa.field("operation_id", pa.string(), nullable=False),
        pa.field("target_id", pa.string(), nullable=False),
        pa.field("operation", pa.string(), nullable=False),
        pa.field("requested", pa.bool_(), nullable=False),
        pa.field("request_mode", pa.string(), nullable=False),
    ]
)

SOURCE_REQUEST_SCHEMA = pa.schema(
    [
        pa.field("source_request_id", pa.string(), nullable=False),
        pa.field("target_id", pa.string(), nullable=False),
        pa.field("source_role", pa.string(), nullable=False),
        pa.field("source_origin", pa.string(), nullable=False),
        pa.field("retrieval_mode", pa.string(), nullable=False),
        pa.field("request_url", pa.string(), nullable=True),
        pa.field("sequence", pa.int32(), nullable=True),
        pa.field("canonical_path", pa.string(), nullable=True),
    ]
)

OPERATION_INPUT_SCHEMA = pa.schema(
    [
        pa.field("operation_id", pa.string(), nullable=False),
        pa.field("input_ordinal", pa.int32(), nullable=False),
        pa.field("source_request_id", pa.string(), nullable=False),
        pa.field("input_role", pa.string(), nullable=False),
    ]
)

PLAN_RELATION_SCHEMAS = {
    "targets": TARGET_SCHEMA,
    "target_operations": TARGET_OPERATION_SCHEMA,
    "source_requests": SOURCE_REQUEST_SCHEMA,
    "operation_inputs": OPERATION_INPUT_SCHEMA,
}

__all__ = [
    "MATCHER_VERSION",
    "INVENTORY_RELATIONS",
    "PLAN_BUNDLE_SCHEMA_VERSION",
    "PROFILE_SCHEMA_VERSION",
    "OPERATION_INPUT_SCHEMA_VERSION",
    "OPERATION_INPUT_SCHEMA",
    "SOURCE_REQUEST_SCHEMA_VERSION",
    "SOURCE_REQUEST_SCHEMA",
    "TARGET_COLUMNS",
    "TARGET_SCHEMA",
    "TARGET_SCHEMA_VERSION",
    "TARGET_OPERATION_SCHEMA_VERSION",
    "TARGET_OPERATION_SCHEMA",
    "PLAN_RELATION_SCHEMAS",
    "TARGET_PLAN_SCHEMA_VERSION",
]
