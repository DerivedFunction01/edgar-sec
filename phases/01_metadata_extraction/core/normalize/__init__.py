"""Pure normalization of SEC submissions JSON into canonical row shape."""

from __future__ import annotations

from .builder import normalize_submissions, validate_row_shapes
from .filings import (
    FILING_ARRAY_KEYS,
    dedupe_filings,
    normalize_items,
    normalize_submission_files,
    zip_filing_arrays,
)
from .helpers import (
    ACCESSION_RE,
    SEC_ARCHIVE_BASE,
    SEC_SUBMISSIONS_BASE,
    accession_normalized,
    add_anomaly,
    build_archive_url,
    canonical_json,
    normalize_cik_padded,
    resolve_alias,
    sha256_of,
    to_bool,
    to_int,
)
from .profile import (
    ADDRESS_KEYS,
    PROFILE_KEYS,
    address_field,
    normalize_address,
    normalize_former_names,
    zip_listings,
)

__all__ = [
    "ACCESSION_RE",
    "ADDRESS_KEYS",
    "FILING_ARRAY_KEYS",
    "PROFILE_KEYS",
    "SEC_ARCHIVE_BASE",
    "SEC_SUBMISSIONS_BASE",
    "accession_normalized",
    "add_anomaly",
    "address_field",
    "build_archive_url",
    "canonical_json",
    "dedupe_filings",
    "normalize_address",
    "normalize_cik_padded",
    "normalize_former_names",
    "normalize_items",
    "normalize_submission_files",
    "normalize_submissions",
    "resolve_alias",
    "sha256_of",
    "to_bool",
    "to_int",
    "validate_row_shapes",
    "zip_filing_arrays",
    "zip_listings",
]
