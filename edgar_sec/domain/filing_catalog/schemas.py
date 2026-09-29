"""Arrow schemas and version constants for the filing catalog.

The catalog is a pure projection of the Phase 1 ``submission_metadata`` dataset:
``PROFILE_SCHEMA`` borrows its fields by reference rather than restating their
types, so a Phase 1 schema change is detected here at import time instead of
surfacing as a silent column drift at materialization time.

``company_family`` is deliberately absent. Clustering is a Stage B selection
feature (see ``roadmap/refactor_v2/phase_2.md`` decision D2); the v1 README
claimed this column existed, but no v1 code path ever wrote it.
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

# The 22 registrant-level columns borrowed from Phase 1, in projection order,
# followed by the catalog-owned profile version column.
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
    "is_amendment",
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
        ("is_amendment", pa.bool_()),
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

# Stage A emits the narrow locator projection. Stage B widens this with the
# feature dimensions (form_family, era, size_band, ...); see phase_2.md 3.4.
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

# The Stage B (policy) widening: the same eight identity columns plus the ten
# stratification dimensions a selection can be audited against. Declared here,
# in the order the published file uses, so the writer and any consumer share
# one ordering rather than each keeping a copy of the list.
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
    "company_name",
)

LOCATOR_POLICY_COLUMNS = (
    "document_locator_key",
    "form",
    "form_family",
    "era",
    "suffix",
    "xbrl_state",
    "size_band",
    "owner_org_presence",
    "foreign_status",
    "lifecycle_class",
    "stub_suspect",
    "representative_cik",
    "representative_accession",
    "primary_document",
    "document_path",
    "archive_url",
    "document_path_source",
    "company_name",
)

__all__ = [
    "DATASET_NAME",
    "LOCATOR_BASE_COLUMNS",
    "LOCATOR_POLICY_COLUMNS",
    "LOCATOR_POLICY_FEATURES",
    "PATH_SOURCE_BUNDLE",
    "PATH_SOURCE_PRIMARY",
    "PROFILE_COLUMNS",
    "PROFILE_SCHEMA",
    "PROFILE_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "SUBMISSION_METADATA_SCHEMA",
    "TARGET_COLUMNS",
    "TARGET_SCHEMA",
    "TARGET_SCHEMA_VERSION",
]
