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
TARGET_PLAN_SCHEMA_VERSION = "1.3"
READABLE_TARGET_PLAN_SCHEMA_VERSIONS = frozenset({"1.2", TARGET_PLAN_SCHEMA_VERSION})

# Provenance of an effective document path in the filing catalog.
PATH_SOURCE_PRIMARY = "primary_document"
PATH_SOURCE_BUNDLE = "submission_bundle"

# The two planning scopes, published under different occurrence schemas, so a scope is
# part of every contract reading a bundle. Declared here because planner and publication
# must name them alike.
SCOPE_DETERMINISTIC = "deterministic"
SCOPE_POLICY = "policy"

# This ordered projection deliberately excludes filing-level source fields.
_PROFILE_EXTENSION = "profile_schema_version"
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
    _PROFILE_EXTENSION,
)

PROFILE_SCHEMA = pa.schema(
    [SUBMISSION_METADATA_SCHEMA.field(name) for name in PROFILE_COLUMNS[:-1]]
    + [(PROFILE_COLUMNS[-1], pa.string())]
)

# Leaf groups own each feature column name. Public layouts below only compose groups.
_OCCURRENCE_ID = ("occurrence_id",)
_LOCATOR_ID = ("document_locator_key",)
_REGISTRANT_ID = ("source_cik", "accession")
_FORM = ("form",)
_FORM_FAMILY = ("form_family",)
_FILING_DATES = ("filing_date", "report_date")
_ERA = ("era",)
_SUFFIX = ("suffix",)
_DOCUMENT_SOURCE = (
    "primary_document",
    "document_path",
    "archive_url",
    "document_path_source",
)
_REPORTED_SIZE = ("reported_size",)
_SIZE_BAND = ("size_band",)
_XBRL_FLAGS = ("is_xbrl", "is_inline_xbrl", "is_xbrl_numeric")
_STUB_SUSPECT = ("stub_suspect",)
_XBRL_STATE = ("xbrl_state",)
_SIC = ("sic_code",)
_OWNER_ORG = ("owner_org_presence",)
_FOREIGN_STATUS = ("foreign_status",)
_FOREIGN_COUNTRY = ("foreign_country_code",)
_STATE_OF_INCORPORATION = ("state_of_incorporation",)
_ENTITY_TYPE = ("entity_type",)
_FILER_CATEGORY = ("filer_category_primary",)
_COMPANY_FAMILY = ("company_family",)
_HAS_REVIVAL_GAP = ("has_revival_gap",)
_LIFECYCLE_CLASS = ("lifecycle_class",)
_LOCATOR_CLASS = ("locator_class",)
_REPRESENTATIVE_ID = ("representative_cik", "representative_accession")

TARGET_COLUMNS = (
    *_OCCURRENCE_ID,
    *_LOCATOR_ID,
    *_REGISTRANT_ID,
    *_FORM,
    *_FILING_DATES,
    *_DOCUMENT_SOURCE,
    *_REPORTED_SIZE,
    *_XBRL_FLAGS,
)
_TARGET_TYPES = (
    *(pa.string() for _ in (*_OCCURRENCE_ID, *_LOCATOR_ID, *_REGISTRANT_ID, *_FORM)),
    *(pa.string() for _ in _FILING_DATES),
    *(pa.string() for _ in _DOCUMENT_SOURCE),
    pa.int64(),
    *(pa.bool_() for _ in _XBRL_FLAGS),
)
TARGET_SCHEMA = pa.schema(zip(TARGET_COLUMNS, _TARGET_TYPES, strict=True))

LOCATOR_BASE_COLUMNS = (
    *_LOCATOR_ID,
    *_FORM,
    *_REPRESENTATIVE_ID,
    *_DOCUMENT_SOURCE,
)

LOCATOR_POLICY_FEATURES = (
    *_FORM_FAMILY,
    *_ERA,
    *_SUFFIX,
    *_XBRL_STATE,
    *_SIZE_BAND,
    *_OWNER_ORG,
    *_FOREIGN_STATUS,
    *_LIFECYCLE_CLASS,
    *_STUB_SUSPECT,
    *_SIC,
)
LOCATOR_POLICY_COLUMNS = LOCATOR_BASE_COLUMNS + LOCATOR_POLICY_FEATURES

LOCATOR_FEATURE_COLUMNS = (
    *_LOCATOR_ID,
    *_FORM,
    *_FORM_FAMILY,
    *_ERA,
    *_SUFFIX,
    *_XBRL_STATE,
    *_SIZE_BAND,
    *_OWNER_ORG,
    *_FOREIGN_STATUS,
    *_FOREIGN_COUNTRY,
    *_ENTITY_TYPE,
    *_FILER_CATEGORY,
    *_LIFECYCLE_CLASS,
    *_HAS_REVIVAL_GAP,
    *_LOCATOR_CLASS,
    *_STUB_SUSPECT,
    *_REPORTED_SIZE,
    *_FILING_DATES,
    *_DOCUMENT_SOURCE,
    *_REPRESENTATIVE_ID,
    *_SIC,
    *_COMPANY_FAMILY,
)

OCCURRENCE_FEATURE_COLUMNS = (
    *_OCCURRENCE_ID,
    *_LOCATOR_ID,
    *_REGISTRANT_ID,
    *_FORM,
    *_FORM_FAMILY,
    *_FILING_DATES,
    *_ERA,
    *_SUFFIX,
    *_DOCUMENT_SOURCE,
    *_REPORTED_SIZE,
    *_SIZE_BAND,
    *_XBRL_FLAGS,
    *_STUB_SUSPECT,
    *_XBRL_STATE,
    *_SIC,
    *_OWNER_ORG,
    *_FOREIGN_STATUS,
    *_FOREIGN_COUNTRY,
    *_STATE_OF_INCORPORATION,
    *_ENTITY_TYPE,
    *_FILER_CATEGORY,
    *_COMPANY_FAMILY,
    *_HAS_REVIVAL_GAP,
    *_LIFECYCLE_CLASS,
)

_OCCURRENCE_DYNAMIC = frozenset((*_SIZE_BAND, *_HAS_REVIVAL_GAP, *_LIFECYCLE_CLASS))
OCCURRENCE_DYNAMIC_COLUMNS = tuple(
    column for column in OCCURRENCE_FEATURE_COLUMNS if column in _OCCURRENCE_DYNAMIC
)
OCCURRENCE_INDEPENDENT_COLUMNS = tuple(
    column for column in OCCURRENCE_FEATURE_COLUMNS if column not in _OCCURRENCE_DYNAMIC
)

__all__ = [
    "DATASET_NAME",
    "LOCATOR_BASE_COLUMNS",
    "LOCATOR_FEATURE_COLUMNS",
    "LOCATOR_POLICY_COLUMNS",
    "LOCATOR_POLICY_FEATURES",
    "OCCURRENCE_FEATURE_COLUMNS",
    "OCCURRENCE_INDEPENDENT_COLUMNS",
    "OCCURRENCE_DYNAMIC_COLUMNS",
    "PATH_SOURCE_BUNDLE",
    "PATH_SOURCE_PRIMARY",
    "PROFILE_COLUMNS",
    "PROFILE_SCHEMA",
    "PROFILE_SCHEMA_VERSION",
    "READABLE_TARGET_PLAN_SCHEMA_VERSIONS",
    "SCHEMA_VERSION",
    "SCOPE_DETERMINISTIC",
    "SCOPE_POLICY",
    "SUBMISSION_METADATA_SCHEMA",
    "TARGET_COLUMNS",
    "TARGET_SCHEMA",
    "TARGET_SCHEMA_VERSION",
    "TARGET_PLAN_SCHEMA_VERSION",
]
