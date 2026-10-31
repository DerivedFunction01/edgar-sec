"""Arrow schemas for published document acquisition snapshots."""

from __future__ import annotations

import pyarrow as pa

from edgar_sec.pipelines.document_acquisition.schemas import TARGET_SCHEMA

SNAPSHOT_SCHEMA_VERSION = 1

ACCESSION_CIKS_SCHEMA = pa.schema(
    [
        pa.field("accession", pa.string(), nullable=False),
        pa.field("cik", pa.string(), nullable=False),
    ]
)

SOURCE_ASSETS_SCHEMA = pa.schema(
    [
        pa.field("source_asset_id", pa.string(), nullable=False),
        pa.field("accession", pa.string(), nullable=False),
        pa.field("source_key", pa.string(), nullable=False),
        pa.field("source_kind", pa.string(), nullable=False),
        pa.field("retrieval_mode", pa.string(), nullable=False),
        pa.field("canonical_path", pa.string(), nullable=True),
    ]
)

ACQUISITION_SLOTS_SCHEMA = pa.schema(
    [
        pa.field("accession", pa.string(), nullable=False),
        pa.field("sequence", pa.int32(), nullable=False),
        pa.field("observation_id", pa.string(), nullable=False),
        pa.field("source_asset_id", pa.string(), nullable=False),
        pa.field("locator", pa.string(), nullable=False),
        pa.field("retrieval_mode", pa.string(), nullable=False),
        pa.field("observed_at_utc", pa.timestamp("us", tz="UTC"), nullable=False),
    ]
)

SLOT_TYPES_SCHEMA = pa.schema(
    [
        pa.field("type_evidence_id", pa.string(), nullable=False),
        pa.field("accession", pa.string(), nullable=False),
        pa.field("sequence", pa.int32(), nullable=False),
        pa.field("observation_id", pa.string(), nullable=True),
        pa.field("statutory_type", pa.string(), nullable=False),
        pa.field("evidence_source", pa.string(), nullable=False),
        pa.field("evidence_ref", pa.string(), nullable=False),
        pa.field("source_digest", pa.string(), nullable=True),
        pa.field("parser_version", pa.string(), nullable=False),
        pa.field("observed_at_utc", pa.timestamp("us", tz="UTC"), nullable=False),
    ]
)

LOGICAL_DOCUMENTS_SCHEMA = pa.schema(
    [
        pa.field("logical_document_id", pa.string(), nullable=False),
        pa.field("accession", pa.string(), nullable=False),
        pa.field("request_id", pa.string(), nullable=False),
        pa.field("planned_source_key", pa.string(), nullable=False),
        pa.field("target_role", pa.string(), nullable=False),
        pa.field("target_type", pa.string(), nullable=False),
    ]
)

TARGET_RESULTS_SCHEMA = pa.schema(
    [
        pa.field("run_id", pa.string(), nullable=False),
        *TARGET_SCHEMA,
        pa.field("logical_document_id", pa.string(), nullable=True),
        pa.field("outcome", pa.string(), nullable=False),
        pa.field("status_reason", pa.string(), nullable=True),
        pa.field("source_asset_id", pa.string(), nullable=True),
        pa.field("selected_sha256", pa.string(), nullable=True),
        pa.field("byte_size", pa.int64(), nullable=True),
    ]
)

TARGET_SLOT_SELECTIONS_SCHEMA = pa.schema(
    [
        pa.field("run_id", pa.string(), nullable=False),
        pa.field("target_id", pa.string(), nullable=False),
        pa.field("resolution_id", pa.string(), nullable=False),
        pa.field("logical_document_id", pa.string(), nullable=False),
        pa.field("accession", pa.string(), nullable=False),
        pa.field("sequence", pa.int32(), nullable=False),
        pa.field("observation_id", pa.string(), nullable=True),
        pa.field("source_asset_id", pa.string(), nullable=True),
        pa.field("selector", pa.string(), nullable=False),
        pa.field("result", pa.string(), nullable=False),
        pa.field("evidence_ref", pa.string(), nullable=True),
    ]
)

ACQUISITION_ATTEMPTS_SCHEMA = pa.schema(
    [
        pa.field("run_id", pa.string(), nullable=False),
        pa.field("attempt_id", pa.string(), nullable=False),
        pa.field("target_id", pa.string(), nullable=False),
        pa.field("source_request_id", pa.string(), nullable=True),
        pa.field("source_asset_id", pa.string(), nullable=True),
        pa.field("attempt_number", pa.int32(), nullable=False),
        pa.field("worker_attempt_number", pa.int32(), nullable=True),
        pa.field("attempt_kind", pa.string(), nullable=False),
        pa.field("origin", pa.string(), nullable=False),
        pa.field("outcome", pa.string(), nullable=False),
        pa.field("retryable", pa.bool_(), nullable=False),
        pa.field("sanitized_locator", pa.string(), nullable=True),
        pa.field("http_status", pa.int32(), nullable=True),
        pa.field("response_sha256", pa.string(), nullable=True),
        pa.field("response_byte_size", pa.int64(), nullable=True),
        pa.field("selected_sha256", pa.string(), nullable=True),
        pa.field("selected_byte_size", pa.int64(), nullable=True),
        pa.field("created_at_utc", pa.timestamp("us", tz="UTC"), nullable=False),
    ]
)

SOURCE_PAYLOADS_SCHEMA = pa.schema(
    [
        pa.field("source_asset_id", pa.string(), nullable=False),
        pa.field("payload_sha256", pa.string(), nullable=False),
    ]
)

OPERATION_RESULTS_SCHEMA = pa.schema(
    [
        pa.field("run_id", pa.string(), nullable=False),
        pa.field("operation_id", pa.string(), nullable=False),
        pa.field("target_id", pa.string(), nullable=False),
        pa.field("logical_document_id", pa.string(), nullable=True),
        pa.field("operation", pa.string(), nullable=False),
        pa.field("requested", pa.bool_(), nullable=False),
        pa.field("support_status", pa.string(), nullable=False),
        pa.field("status", pa.string(), nullable=False),
        pa.field("source_request_id", pa.string(), nullable=True),
        pa.field("capability_id", pa.string(), nullable=True),
        pa.field("capability_version", pa.string(), nullable=True),
        pa.field("handler_id", pa.string(), nullable=True),
        pa.field("handler_version", pa.string(), nullable=True),
        pa.field("latest_attempt_id", pa.string(), nullable=True),
        pa.field("reason_code", pa.string(), nullable=True),
        pa.field("retryable", pa.bool_(), nullable=False),
        pa.field("representation_id", pa.string(), nullable=True),
    ]
)

OPERATION_ATTEMPTS_SCHEMA = pa.schema(
    [
        pa.field("run_id", pa.string(), nullable=False),
        pa.field("operation_attempt_id", pa.string(), nullable=False),
        pa.field("operation_id", pa.string(), nullable=False),
        pa.field("attempt_number", pa.int32(), nullable=False),
        pa.field("attempt_kind", pa.string(), nullable=False),
        pa.field("input_fingerprint", pa.string(), nullable=False),
        pa.field("capability_id", pa.string(), nullable=True),
        pa.field("capability_version", pa.string(), nullable=True),
        pa.field("handler_id", pa.string(), nullable=True),
        pa.field("handler_version", pa.string(), nullable=True),
        pa.field("options_sha256", pa.string(), nullable=True),
        pa.field("status", pa.string(), nullable=False),
        pa.field("error_code", pa.string(), nullable=True),
        pa.field("input_sha256", pa.string(), nullable=True),
        pa.field("input_byte_size", pa.int64(), nullable=True),
        pa.field("output_sha256", pa.string(), nullable=True),
        pa.field("output_byte_size", pa.int64(), nullable=True),
    ]
)

REPRESENTATIONS_SCHEMA = pa.schema(
    [
        pa.field("representation_id", pa.string(), nullable=False),
        pa.field("logical_document_id", pa.string(), nullable=False),
        pa.field("operation", pa.string(), nullable=False),
        pa.field("output_kind", pa.string(), nullable=False),
        pa.field("capability_id", pa.string(), nullable=False),
        pa.field("capability_version", pa.string(), nullable=False),
        pa.field("handler_id", pa.string(), nullable=False),
        pa.field("handler_version", pa.string(), nullable=False),
        pa.field("options_sha256", pa.string(), nullable=True),
        pa.field("input_fingerprint", pa.string(), nullable=False),
        pa.field("output_sha256", pa.string(), nullable=False),
        pa.field("byte_size", pa.int64(), nullable=False),
        pa.field("route", pa.string(), nullable=False),
    ]
)

REPRESENTATION_INPUTS_SCHEMA = pa.schema(
    [
        pa.field("representation_id", pa.string(), nullable=False),
        pa.field("input_ordinal", pa.int32(), nullable=False),
        pa.field("source_asset_id", pa.string(), nullable=False),
        pa.field("payload_sha256", pa.string(), nullable=False),
        pa.field("input_role", pa.string(), nullable=False),
    ]
)

PAYLOAD_INDEX_SCHEMA = pa.schema(
    [
        pa.field("payload_sha256", pa.string(), nullable=False),
        pa.field("storage_class", pa.string(), nullable=False),
        pa.field("byte_size", pa.int64(), nullable=False),
    ]
)

BINARY_PAYLOADS_SCHEMA = pa.schema(
    [
        pa.field("payload_sha256", pa.string(), nullable=False),
        pa.field("payload_bytes", pa.large_binary(), nullable=False),
    ]
)

TEXT_PAYLOADS_SCHEMA = pa.schema(
    [
        pa.field("payload_sha256", pa.string(), nullable=False),
        pa.field("payload_bytes", pa.large_binary(), nullable=False),
        pa.field("text_value", pa.string(), nullable=True),
    ]
)

DOCUMENT_SECTIONS_SCHEMA = pa.schema(
    [
        pa.field("accession", pa.string(), nullable=False),
        pa.field("logical_document_id", pa.string(), nullable=False),
        pa.field("representation_id", pa.string(), nullable=False),
        pa.field("payload_sha256", pa.string(), nullable=False),
        pa.field("renderer_version", pa.string(), nullable=False),
        pa.field("form", pa.string(), nullable=False),
        pa.field("item_identifier", pa.string(), nullable=False),
        pa.field("canonical_name", pa.string(), nullable=False),
        pa.field("heading", pa.string(), nullable=False),
        pa.field("start_line", pa.int32(), nullable=False),
        pa.field("end_line", pa.int32(), nullable=False),
        pa.field("is_omitted", pa.bool_(), nullable=False),
    ]
)

DOCUMENT_NOTES_SCHEMA = pa.schema(
    [
        pa.field("accession", pa.string(), nullable=False),
        pa.field("logical_document_id", pa.string(), nullable=False),
        pa.field("representation_id", pa.string(), nullable=False),
        pa.field("payload_sha256", pa.string(), nullable=False),
        pa.field("renderer_version", pa.string(), nullable=False),
        pa.field("form", pa.string(), nullable=False),
        pa.field("note_number", pa.int32(), nullable=False),
        pa.field("note_label", pa.string(), nullable=False),
        pa.field("heading", pa.string(), nullable=False),
        pa.field("start_line", pa.int32(), nullable=False),
        pa.field("end_line", pa.int32(), nullable=False),
    ]
)

SNAPSHOT_RELATION_SCHEMAS = {
    "accession_ciks": ACCESSION_CIKS_SCHEMA,
    "source_assets": SOURCE_ASSETS_SCHEMA,
    "acquisition_slots": ACQUISITION_SLOTS_SCHEMA,
    "slot_types": SLOT_TYPES_SCHEMA,
    "logical_documents": LOGICAL_DOCUMENTS_SCHEMA,
    "target_results": TARGET_RESULTS_SCHEMA,
    "target_slot_selections": TARGET_SLOT_SELECTIONS_SCHEMA,
    "acquisition_attempts": ACQUISITION_ATTEMPTS_SCHEMA,
    "source_payloads": SOURCE_PAYLOADS_SCHEMA,
    "operation_results": OPERATION_RESULTS_SCHEMA,
    "operation_attempts": OPERATION_ATTEMPTS_SCHEMA,
    "representations": REPRESENTATIONS_SCHEMA,
    "representation_inputs": REPRESENTATION_INPUTS_SCHEMA,
    "payload_index": PAYLOAD_INDEX_SCHEMA,
    "binary_payloads": BINARY_PAYLOADS_SCHEMA,
    "text_payloads": TEXT_PAYLOADS_SCHEMA,
    "document_sections": DOCUMENT_SECTIONS_SCHEMA,
    "document_notes": DOCUMENT_NOTES_SCHEMA,
}

__all__ = [
    "ACCESSION_CIKS_SCHEMA",
    "ACQUISITION_ATTEMPTS_SCHEMA",
    "ACQUISITION_SLOTS_SCHEMA",
    "BINARY_PAYLOADS_SCHEMA",
    "DOCUMENT_NOTES_SCHEMA",
    "DOCUMENT_SECTIONS_SCHEMA",
    "LOGICAL_DOCUMENTS_SCHEMA",
    "OPERATION_ATTEMPTS_SCHEMA",
    "OPERATION_RESULTS_SCHEMA",
    "PAYLOAD_INDEX_SCHEMA",
    "REPRESENTATIONS_SCHEMA",
    "REPRESENTATION_INPUTS_SCHEMA",
    "SLOT_TYPES_SCHEMA",
    "SNAPSHOT_RELATION_SCHEMAS",
    "SNAPSHOT_SCHEMA_VERSION",
    "SOURCE_ASSETS_SCHEMA",
    "SOURCE_PAYLOADS_SCHEMA",
    "TARGET_RESULTS_SCHEMA",
    "TARGET_SLOT_SELECTIONS_SCHEMA",
    "TEXT_PAYLOADS_SCHEMA",
]
