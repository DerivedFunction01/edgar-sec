"""DDL and SQL query construction for Phase 2 catalog snapshot materialization."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from defs.filing_identity import (
    accession_hyphenated,
    document_locator_key,
    full_submission_url_for,
    is_amendment_form,
    normalize_accession,
    occurrence_id,
    parse_archive_url,
)

from ..schemas import (
    PATH_SOURCE_BUNDLE,
    PATH_SOURCE_PRIMARY,
    PROFILE_COLUMNS,
    PROFILE_SCHEMA_VERSION,
)

_RE_INVALID_CHARS = re.compile(r"[^A-Za-z0-9_.-]")
_EffectiveParts = tuple[str, str, str]  # (document_path, archive_url, source)


def _effective_document_parts(
    primary_document: object, archive_url: object, cik: object, accession: object
) -> _EffectiveParts | None:
    if archive_url:
        parts = parse_archive_url(str(archive_url))
        if parts is not None:
            return parts.document_path, parts.url, PATH_SOURCE_PRIMARY
    canonical = normalize_accession(str(accession) if accession else None)
    cik_text = str(cik).strip() if cik is not None else ""
    if canonical is None or not cik_text.isdigit():
        return None
    try:
        bundle_url = full_submission_url_for(cik_text, canonical)
    except ValueError:
        return None
    return f"{accession_hyphenated(canonical)}.txt", bundle_url, PATH_SOURCE_BUNDLE


def _effective_path(
    primary_document: object, archive_url: object, cik: object, accession: object
) -> str | None:
    parts = _effective_document_parts(primary_document, archive_url, cik, accession)
    return None if parts is None else parts[0]


def _effective_archive_url(
    primary_document: object, archive_url: object, cik: object, accession: object
) -> str | None:
    parts = _effective_document_parts(primary_document, archive_url, cik, accession)
    return None if parts is None else parts[1]


def _effective_source(
    primary_document: object, archive_url: object, cik: object, accession: object
) -> str | None:
    parts = _effective_document_parts(primary_document, archive_url, cik, accession)
    return None if parts is None else parts[2]


def _safe_occurrence(cik, accession, path):
    try:
        return occurrence_id(cik or "", accession or "", path)
    except ValueError:
        return None


def _safe_locator(accession, path):
    try:
        return document_locator_key(accession or "", path)
    except ValueError:
        return None


def partition_key(form: str | None) -> str:
    """Normalize form names into safe partition path directory components."""
    value = str(form or "").strip()
    return _RE_INVALID_CHARS.sub("_", value) or "_unknown"


def register_identity_functions(artifact) -> None:
    """Register Python UDFs for DuckDB."""
    artifact.register_function(
        "filing_accession", normalize_accession, parameters=[str], return_type=str
    )
    artifact.register_function(
        "filing_document_path",
        lambda value: (
            parse_archive_url(value).document_path if parse_archive_url(value) else None
        ),
        parameters=[str],
        return_type=str,
    )
    artifact.register_function(
        "filing_effective_path",
        _effective_path,
        parameters=[str, str, str, str],
        return_type=str,
    )
    artifact.register_function(
        "filing_effective_archive_url",
        _effective_archive_url,
        parameters=[str, str, str, str],
        return_type=str,
    )
    artifact.register_function(
        "filing_effective_source",
        _effective_source,
        parameters=[str, str, str, str],
        return_type=str,
    )
    artifact.register_function(
        "filing_occurrence_id",
        _safe_occurrence,
        parameters=[str, str, str],
        return_type=str,
    )
    artifact.register_function(
        "filing_locator_key", _safe_locator, parameters=[str, str], return_type=str
    )
    artifact.register_function(
        "filing_is_amendment", is_amendment_form, parameters=[str], return_type=bool
    )
    artifact.register_function(
        "filing_partition_key", partition_key, parameters=[str], return_type=str
    )


def build_profile_query(relation: str) -> str:
    """Construct deduplicated company profile extraction query matching schema."""
    profile_cols = ", ".join(f'"{c}"' for c in PROFILE_COLUMNS[:-1])
    return f"""
    SELECT
        {profile_cols},
        '{PROFILE_SCHEMA_VERSION}' AS profile_schema_version
    FROM (
        SELECT *,
               ROW_NUMBER() OVER (
                   PARTITION BY cik
                   ORDER BY fetched_at DESC NULLS LAST
               ) AS rn
        FROM {relation}
        WHERE cik IS NOT NULL
    ) ranked
    WHERE rn = 1
    ORDER BY cik
    """


def build_batch_query(relation: str, metadata_sql: str) -> str:
    """Construct SQL query for unnesting and streaming filing targets for a CIK range."""
    return f"""
    SELECT
        filing_occurrence_id(s.source_cik, s.accession, s.document_path) AS occurrence_id,
        filing_locator_key(s.accession, s.document_path) AS document_locator_key,
        s.source_cik,
        s.accession,
        s.form,
        filing_partition_key(s.form) AS form_partition_key,
        filing_is_amendment(s.form) AS is_amendment,
        s.filing_date,
        s.report_date,
        s.acceptance_datetime,
        s.primary_document,
        s.primary_doc_description,
        s.document_path,
        s.archive_url,
        s.document_path_source,
        s.source_section,
        s.source_file,
        s.source_array_index,
        s.reported_size,
        s.is_xbrl,
        s.is_inline_xbrl,
        s.is_xbrl_numeric,
        {metadata_sql}
    FROM (
        SELECT
            t.cik AS source_cik,
            filing_accession(filing.accession_number_normalized) AS accession,
            filing.form AS form,
            filing.filing_date AS filing_date,
            filing.report_date AS report_date,
            filing.acceptance_datetime AS acceptance_datetime,
            filing.primary_document AS primary_document,
            filing.primary_doc_description AS primary_doc_description,
            filing_effective_path(
                filing.primary_document, filing.archive_url,
                t.cik, filing.accession_number_normalized
            ) AS document_path,
            filing_effective_archive_url(
                filing.primary_document, filing.archive_url,
                t.cik, filing.accession_number_normalized
            ) AS archive_url,
            filing_effective_source(
                filing.primary_document, filing.archive_url,
                t.cik, filing.accession_number_normalized
            ) AS document_path_source,
            filing.source_section AS source_section,
            filing.source_file AS source_file,
            filing.source_array_index AS source_array_index,
            filing.size AS reported_size,
            filing.is_xbrl AS is_xbrl,
            filing.is_inline_xbrl AS is_inline_xbrl,
            filing.is_xbrl_numeric AS is_xbrl_numeric
        FROM {relation} AS t, LATERAL unnest(t.filings) AS u(filing)
        WHERE t.cik >= ? AND t.cik <= ?
          AND filing.form IS NOT NULL
          AND filing_effective_path(
                  filing.primary_document, filing.archive_url,
                  t.cik, filing.accession_number_normalized
              ) IS NOT NULL
    ) AS s
    WHERE s.accession IS NOT NULL
    """


def build_sources_query(target_parquet_files: Iterable[Path]) -> str:
    """Construct SQL query for distinct filing occurrence sources."""
    files_str = ", ".join(f"'{p}'" for p in target_parquet_files)
    return f"""
    SELECT DISTINCT
        occurrence_id,
        source_cik,
        accession,
        document_path,
        source_section,
        source_file,
        source_array_index
    FROM read_parquet([{files_str}])
    ORDER BY accession, source_cik
    """


__all__ = [
    "build_batch_query",
    "build_profile_query",
    "build_sources_query",
    "partition_key",
    "register_identity_functions",
]
