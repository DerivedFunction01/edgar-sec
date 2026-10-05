"""Arrow schemas and version constants for the filing catalog.

``PROFILE_SCHEMA`` borrows the Phase 1 ``submission_metadata`` fields by reference, so a
Phase 1 change surfaces here at import time rather than as column drift later.
"""

from __future__ import annotations

import pyarrow as pa

from edgar_sec.domain.submissions.schemas import SUBMISSION_METADATA_SCHEMA

DATASET_NAME = "filing_catalog"

# Bump on a breaking change to TARGET_SCHEMA or PROFILE_SCHEMA respectively.
SCHEMA_VERSION = "1.1.0"
TARGET_SCHEMA_VERSION = "1.1.0"
PROFILE_SCHEMA_VERSION = "1.0.0"

# Provenance of an effective document path in the filing catalog.
PATH_SOURCE_PRIMARY = "primary_document"
PATH_SOURCE_BUNDLE = "submission_bundle"

# The two planning scopes, published under different occurrence schemas, so a scope is
# part of every contract reading a bundle. Declared here because planner and publication
# must name them alike.
SCOPE_DETERMINISTIC = "deterministic"
SCOPE_POLICY = "policy"

# The registrant-level columns borrowed from the submissions schema, in
# projection order, followed by the catalog-owned profile version column.
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

TARGET_COLUMNS = (
    "occurrence_id",
    "document_locator_key",
    "source_cik",
    "accession",
    "form",
    "filing_date",
    "report_date",
    "primary_document",
    "document_path",
    "archive_url",
    "document_path_source",
    "reported_size",
    "is_xbrl",
    "is_inline_xbrl",
    "is_xbrl_numeric",
)

PROFILE_SCHEMA = pa.schema(
    [SUBMISSION_METADATA_SCHEMA.field(name) for name in PROFILE_COLUMNS[:-1]]
    + [("profile_schema_version", pa.string())]
)

TARGET_SCHEMA = pa.schema(
    [
        ("occurrence_id", pa.string()),
        ("document_locator_key", pa.string()),
        ("source_cik", pa.string()),
        ("accession", pa.string()),
        ("form", pa.string()),
        ("filing_date", pa.string()),
        ("report_date", pa.string()),
        ("primary_document", pa.string()),
        ("document_path", pa.string()),
        ("archive_url", pa.string()),
        ("document_path_source", pa.string()),
        ("reported_size", pa.int64()),
        ("is_xbrl", pa.bool_()),
        ("is_inline_xbrl", pa.bool_()),
        ("is_xbrl_numeric", pa.bool_()),
    ]
)

# Deterministic scope emits the narrow locator projection; policy scope widens it with
# LOCATOR_POLICY_FEATURES.
LOCATOR_BASE_COLUMNS = (
    "document_locator_key",
    "form",
    "representative_cik",
    "representative_accession",
    "primary_document",
    "document_path",
    "archive_url",
    "document_path_source",
)

# The policy-scope widening: locator identity columns plus the stratification dimensions a
# selection is audited against, in published order so writer and consumers share one list.
LOCATOR_POLICY_FEATURES = (
    "form_family",
    "era",
    "suffix",
    "xbrl_state",
    "size_band",
    "owner_org_presence",
    "foreign_status",
    "lifecycle_class",
    "stub_suspect",
    "sic_code",
)

LOCATOR_POLICY_COLUMNS = LOCATOR_BASE_COLUMNS + LOCATOR_POLICY_FEATURES

OCCURRENCE_FEATURE_COLUMNS = (
    "occurrence_id",
    "document_locator_key",
    "source_cik",
    "accession",
    "form",
    "form_family",
    "filing_date",
    "report_date",
    "era",
    "suffix",
    "primary_document",
    "document_path",
    "archive_url",
    "document_path_source",
    "reported_size",
    "size_band",
    "is_xbrl",
    "is_inline_xbrl",
    "is_xbrl_numeric",
    "stub_suspect",
    "xbrl_state",
    "sic_code",
    "owner_org_presence",
    "foreign_status",
    "foreign_country_code",
    "state_of_incorporation",
    "entity_type",
    "filer_category_primary",
    "company_family",
    "has_revival_gap",
    "lifecycle_class",
)

LOCATOR_FEATURE_COLUMNS = (
    "document_locator_key",
    "form",
    "form_family",
    "era",
    "suffix",
    "xbrl_state",
    "size_band",
    "owner_org_presence",
    "foreign_status",
    "foreign_country_code",
    "entity_type",
    "filer_category_primary",
    "lifecycle_class",
    "has_revival_gap",
    "locator_class",
    "stub_suspect",
    "reported_size",
    "filing_date",
    "report_date",
    "primary_document",
    "document_path",
    "archive_url",
    "document_path_source",
    "representative_cik",
    "representative_accession",
    "sic_code",
    "company_family",
)

__all__ = [
    "DATASET_NAME",
    "LOCATOR_BASE_COLUMNS",
    "LOCATOR_FEATURE_COLUMNS",
    "LOCATOR_POLICY_COLUMNS",
    "LOCATOR_POLICY_FEATURES",
    "OCCURRENCE_FEATURE_COLUMNS",
    "PATH_SOURCE_BUNDLE",
    "PATH_SOURCE_PRIMARY",
    "PROFILE_COLUMNS",
    "PROFILE_SCHEMA",
    "PROFILE_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "SCOPE_DETERMINISTIC",
    "SCOPE_POLICY",
    "SUBMISSION_METADATA_SCHEMA",
    "TARGET_COLUMNS",
    "TARGET_SCHEMA",
    "TARGET_SCHEMA_VERSION",
]
