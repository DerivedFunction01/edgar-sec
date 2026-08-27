"""Explicit PyArrow schema for the canonical submission_metadata dataset.

One row per CIK. Nested values use explicit ``struct``/``list<struct>`` types
so empty arrays, nulls, and empty objects remain distinguishable; canonical
JSON is used only for ``extra_fields`` and anomaly details. Declared once
here to avoid pandas-inferred schema drift between empty, failed, and
successful chunks.
"""

from __future__ import annotations

import pyarrow as pa

DATASET_NAME = "submission_metadata"
SCHEMA_VERSION = "1.0.0"

ADDRESS_STRUCT = pa.struct(
    [
        ("street1", pa.string()),
        ("street2", pa.string()),
        ("city", pa.string()),
        ("state_or_country", pa.string()),
        ("zip_code", pa.string()),
        ("state_or_country_description", pa.string()),
    ]
)

FORMER_NAME_STRUCT = pa.struct(
    [
        ("name", pa.string()),
        ("from_date", pa.string()),
        ("to_date", pa.string()),
    ]
)

LISTING_STRUCT = pa.struct(
    [
        ("ticker", pa.string()),
        ("exchange", pa.string()),
    ]
)

ANOMALY_STRUCT = pa.struct(
    [
        ("code", pa.string()),
        ("detail", pa.string()),
        ("source", pa.string()),  # top-level key, file name, or accession
    ]
)

FILING_STRUCT = pa.struct(
    [
        ("accession_number", pa.string()),  # SEC hyphenated form
        ("accession_number_normalized", pa.string()),  # validated de-hyphenated form
        ("filing_date", pa.string()),
        ("report_date", pa.string()),
        ("acceptance_datetime", pa.string()),
        ("act", pa.string()),
        ("form", pa.string()),
        ("file_number", pa.string()),
        ("film_number", pa.string()),
        ("items", pa.list_(pa.string())),
        ("core_type", pa.string()),
        ("size", pa.int64()),
        ("is_xbrl", pa.bool_()),
        ("is_inline_xbrl", pa.bool_()),
        ("is_xbrl_numeric", pa.bool_()),
        ("primary_document", pa.string()),
        ("primary_doc_description", pa.string()),
        ("archive_url", pa.string()),
        ("source_section", pa.string()),  # "recent" or historical file name
        ("source_file", pa.string()),  # URL the record was parsed from
        ("source_array_index", pa.int32()),
    ]
)

SUBMISSION_FILE_STRUCT = pa.struct(
    [
        ("name", pa.string()),
        ("filing_count", pa.int32()),
        ("filing_from", pa.string()),
        ("filing_to", pa.string()),
    ]
)

SUBMISSION_METADATA_SCHEMA = pa.schema(
    [
        # Operational metadata
        ("cik", pa.string()),  # ten-digit padded
        ("snapshot_id", pa.string()),
        ("fetched_at", pa.string()),  # ISO-8601 UTC
        ("source_url", pa.string()),
        ("response_sha256", pa.string()),
        ("byte_count", pa.int64()),
        ("schema_version", pa.string()),
        ("status", pa.string()),  # ok | partial | failed
        ("error", pa.string()),  # null unless failed/partial
        ("anomalies", pa.list_(ANOMALY_STRUCT)),
        ("extra_fields", pa.string()),  # canonical JSON; null when none
        # Profile fields grouped into named semantic structs
        ("identity", pa.struct([("name", pa.string()), ("former_names", pa.list_(FORMER_NAME_STRUCT))])),
        (
            "classification",
            pa.struct(
                [
                    ("entity_type", pa.string()),
                    ("sic_code", pa.string()),
                    ("sic_description", pa.string()),
                    ("owner_org", pa.string()),
                    ("filer_category", pa.string()),
                ]
            ),
        ),
        ("identifiers", pa.struct([("ein", pa.string()), ("lei", pa.string())])),
        (
            "contact",
            pa.struct(
                [
                    ("phone", pa.string()),
                    ("website", pa.string()),
                    ("investor_website", pa.string()),
                    ("description", pa.string()),
                ]
            ),
        ),
        (
            "incorporation",
            pa.struct([("state", pa.string()), ("state_description", pa.string())]),
        ),
        ("reporting", pa.struct([("fiscal_year_end", pa.string())])),
        (
            "insider_transactions",
            pa.struct([("owner_exists", pa.bool_()), ("issuer_exists", pa.bool_())]),
        ),
        ("addresses", pa.struct([("mailing", ADDRESS_STRUCT), ("business", ADDRESS_STRUCT)])),
        # Repeated values as typed lists
        ("listings", pa.list_(LISTING_STRUCT)),
        ("filings", pa.list_(FILING_STRUCT)),
        ("submission_files", pa.list_(SUBMISSION_FILE_STRUCT)),
        # Acquisition provenance from the input manifest
        ("input_name", pa.string()),  # never overwrites SEC name
        ("input_fingerprint", pa.string()),
        ("chunk_id", pa.int32()),
        ("historical_files_total", pa.int32()),
        ("historical_files_failed", pa.int32()),
        ("historical_records_total", pa.int32()),
    ]
)

TERMINAL_STATUSES = {"ok", "partial", "failed"}
