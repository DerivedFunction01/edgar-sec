"""Versioned public schemas for the derived filing catalog."""

from __future__ import annotations

import importlib

import pyarrow as pa

SOURCE = importlib.import_module("phases.01_metadata_extraction.core.schemas")
SCHEMA_VERSION = "1.0.0"
PROFILE_SCHEMA_VERSION = "1.0.0"
TARGET_SCHEMA_VERSION = "1.0.0"

PROFILE_COLUMNS = (
    "cik",
    "identity",
    "classification",
    "identifiers",
    "contact",
    "incorporation",
    "reporting",
    "insider_transactions",
    "addresses",
    "listings",
    "input_name",
    "status",
    "error",
    "anomalies",
    "extra_fields",
    "snapshot_id",
    "fetched_at",
    "source_url",
    "response_sha256",
    "byte_count",
    "input_fingerprint",
    "schema_version",
    "profile_schema_version",
)
PROFILE_SCHEMA = pa.schema(
    [SOURCE.SUBMISSION_METADATA_SCHEMA.field(name) for name in PROFILE_COLUMNS[:-1]]
    + [("profile_schema_version", pa.string())]
)

TARGET_COLUMNS = (
    ("occurrence_id", pa.string()),
    ("document_locator_key", pa.string()),
    ("source_cik", pa.string()),
    ("accession", pa.string()),
    ("form", pa.string()),
    ("form_partition_key", pa.string()),
    ("is_amendment", pa.bool_()),
    ("filing_date", pa.string()),
    ("report_date", pa.string()),
    ("acceptance_datetime", pa.string()),
    ("primary_document", pa.string()),
    ("primary_doc_description", pa.string()),
    ("document_path", pa.string()),
    ("archive_url", pa.string()),
    ("source_section", pa.string()),
    ("source_file", pa.string()),
    ("source_array_index", pa.int32()),
    ("reported_size", pa.int64()),
    ("is_xbrl", pa.bool_()),
    ("is_inline_xbrl", pa.bool_()),
    ("is_xbrl_numeric", pa.bool_()),
    ("source_artifact_sha256", pa.string()),
    ("input_fingerprint", pa.string()),
    ("schema_version", pa.string()),
    ("catalog_id", pa.string()),
)
TARGET_SCHEMA = pa.schema(TARGET_COLUMNS)
