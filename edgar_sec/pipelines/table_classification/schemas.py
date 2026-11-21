"""Plan and run-output relation schemas for table classification."""

from __future__ import annotations

import pyarrow as pa

PLAN_FORMAT_VERSION = "1.0.0"
RUN_OUTPUT_VERSION = "1.0.0"

GEOMETRY_EXPECTED = "expected"
GEOMETRY_NONE = "none"
GEOMETRY_EXPECTATIONS = (GEOMETRY_EXPECTED, GEOMETRY_NONE)

ROUTE_RAW = "raw"
ROUTE_RENDER_TO_TXT = "render_to_txt"
ROUTE_RENDER_TO_XML = "render_to_xml"
PROVENANCE_ROUTES = (ROUTE_RAW, ROUTE_RENDER_TO_TXT, ROUTE_RENDER_TO_XML)

STATUS_CLASSIFIED = "classified"
STATUS_NO_GEOMETRIES = "no_geometries"
STATUS_NO_DOCUMENTS = "no_documents"

PROVENANCE_SCHEMA = pa.schema(
    [
        pa.field("plan_format_version", pa.string(), nullable=False),
        pa.field("plan_id", pa.string(), nullable=False),
        pa.field("registry_state", pa.string(), nullable=False),
        pa.field("source_snapshot_id", pa.string(), nullable=False),
        pa.field("normalize_version", pa.string(), nullable=False),
        pa.field("renderer_version", pa.string(), nullable=False),
        pa.field("created_at", pa.string(), nullable=False),
        pa.field("filing_count", pa.int64(), nullable=False),
        pa.field("profile_count", pa.int64(), nullable=False),
        pa.field("target_count", pa.int64(), nullable=False),
        pa.field("work_item_count", pa.int64(), nullable=False),
    ]
)

FILINGS_SCHEMA = pa.schema(
    [
        pa.field("accession", pa.string(), nullable=False),
        pa.field("cik", pa.int64(), nullable=True),
        pa.field("form", pa.string(), nullable=False),
        pa.field("filing_date", pa.string(), nullable=True),
        pa.field("stratum", pa.string(), nullable=True),
    ]
)

PROFILE_APPLICATION_SCHEMA = pa.schema(
    [
        pa.field("accession", pa.string(), nullable=False),
        pa.field("family", pa.string(), nullable=False),
        pa.field("kind", pa.string(), nullable=False),
        pa.field("vocabulary_seat", pa.string(), nullable=False),
    ]
)

DOCUMENT_TARGETS_SCHEMA = pa.schema(
    [
        pa.field("accession", pa.string(), nullable=False),
        pa.field("target_role", pa.string(), nullable=False),
        pa.field("target_type", pa.string(), nullable=False),
        pa.field("optional", pa.bool_(), nullable=False),
        pa.field("document_name", pa.string(), nullable=True),
        pa.field("geometry_expectation", pa.string(), nullable=False),
        pa.field("provenance_route", pa.string(), nullable=False),
    ]
)

WORK_ITEMS_SCHEMA = pa.schema(
    [
        pa.field("work_item_id", pa.string(), nullable=False),
        pa.field("accession", pa.string(), nullable=False),
        pa.field("ordinal", pa.int64(), nullable=False),
    ]
)

PLAN_RELATION_SCHEMAS = {
    "provenance": PROVENANCE_SCHEMA,
    "filings": FILINGS_SCHEMA,
    "profile_application": PROFILE_APPLICATION_SCHEMA,
    "document_targets": DOCUMENT_TARGETS_SCHEMA,
    "work_items": WORK_ITEMS_SCHEMA,
}
PLAN_RELATIONS = tuple(PLAN_RELATION_SCHEMAS)

FILING_RECORDS_SCHEMA = pa.schema(
    [
        pa.field("plan_id", pa.string(), nullable=False),
        pa.field("accession", pa.string(), nullable=False),
        pa.field("cik", pa.int64(), nullable=True),
        pa.field("form", pa.string(), nullable=False),
        pa.field("filing_date", pa.string(), nullable=True),
        pa.field("stratum", pa.string(), nullable=True),
        pa.field("source_snapshot_id", pa.string(), nullable=False),
        pa.field("registry_state", pa.string(), nullable=False),
        pa.field("normalize_version", pa.string(), nullable=False),
        pa.field("renderer_version", pa.string(), nullable=False),
        pa.field("document_count", pa.int64(), nullable=False),
        pa.field("geometry_count", pa.int64(), nullable=False),
        pa.field("classified_count", pa.int64(), nullable=False),
        pa.field("status", pa.string(), nullable=False),
        pa.field("absence_reason", pa.string(), nullable=True),
    ]
)

GEOMETRY_INVENTORY_SCHEMA = pa.schema(
    [
        pa.field("plan_id", pa.string(), nullable=False),
        pa.field("accession", pa.string(), nullable=False),
        pa.field("source_document", pa.string(), nullable=False),
        pa.field("table_index", pa.int64(), nullable=False),
        pa.field("provenance_route", pa.string(), nullable=False),
    ]
)

CLASSIFICATIONS_SCHEMA = pa.schema(
    [
        pa.field("plan_id", pa.string(), nullable=False),
        pa.field("accession", pa.string(), nullable=False),
        pa.field("source_document", pa.string(), nullable=False),
        pa.field("table_index", pa.int64(), nullable=False),
        pa.field("family", pa.string(), nullable=False),
        pa.field("flavor", pa.string(), nullable=True),
        pa.field("kind", pa.string(), nullable=False),
        pa.field("tier", pa.string(), nullable=False),
        pa.field("score", pa.float64(), nullable=False),
        pa.field("assembled_family", pa.string(), nullable=True),
        pa.field("mechanism", pa.string(), nullable=True),
        pa.field("evidence", pa.string(), nullable=False),
    ]
)

OUTPUT_RELATION_SCHEMAS = {
    "filing_records": FILING_RECORDS_SCHEMA,
    "geometry_inventory": GEOMETRY_INVENTORY_SCHEMA,
    "classifications": CLASSIFICATIONS_SCHEMA,
}
OUTPUT_RELATIONS = tuple(OUTPUT_RELATION_SCHEMAS)

GEOMETRY_KEY = ("accession", "source_document", "table_index")

__all__ = [
    "CLASSIFICATIONS_SCHEMA",
    "DOCUMENT_TARGETS_SCHEMA",
    "FILINGS_SCHEMA",
    "FILING_RECORDS_SCHEMA",
    "GEOMETRY_EXPECTATIONS",
    "GEOMETRY_EXPECTED",
    "GEOMETRY_INVENTORY_SCHEMA",
    "GEOMETRY_KEY",
    "GEOMETRY_NONE",
    "OUTPUT_RELATIONS",
    "OUTPUT_RELATION_SCHEMAS",
    "PLAN_FORMAT_VERSION",
    "PLAN_RELATIONS",
    "PLAN_RELATION_SCHEMAS",
    "PROFILE_APPLICATION_SCHEMA",
    "PROVENANCE_ROUTES",
    "PROVENANCE_SCHEMA",
    "ROUTE_RAW",
    "ROUTE_RENDER_TO_TXT",
    "ROUTE_RENDER_TO_XML",
    "RUN_OUTPUT_VERSION",
    "STATUS_CLASSIFIED",
    "STATUS_NO_DOCUMENTS",
    "STATUS_NO_GEOMETRIES",
    "WORK_ITEMS_SCHEMA",
]
