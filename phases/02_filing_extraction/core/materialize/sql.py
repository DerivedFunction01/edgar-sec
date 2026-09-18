"""DDL and SQL query construction for Phase 2 catalog snapshot materialization."""

from __future__ import annotations

from ..schemas import (
    PROFILE_COLUMNS,
    PROFILE_SCHEMA_VERSION,
)


def build_part_unnest_query(part_path: str) -> str:
    return f"""
    WITH raw_unnest AS (
        SELECT
            t.cik AS source_cik,
            sub.f.form AS form,
            sub.f.accession_number AS accession_number,
            sub.f.filing_date AS filing_date,
            sub.f.report_date AS report_date,
            sub.f.primary_document AS primary_document,
            sub.f.archive_url AS archive_url,
            sub.f.size AS size,
            sub.f.is_xbrl AS is_xbrl,
            sub.f.is_inline_xbrl AS is_inline_xbrl,
            sub.f.is_xbrl_numeric AS is_xbrl_numeric
        FROM read_parquet('{part_path}') AS t,
             LATERAL (SELECT UNNEST(t.filings) AS f) AS sub
        WHERE t.filings IS NOT NULL
    ),
    with_derived AS (
        SELECT
            source_cik,
            replace(accession_number, '-', '') AS accession,
            form AS form,
            (upper(form) LIKE '%/A' OR upper(form) LIKE '%_A') AS is_amendment,
            filing_date AS filing_date,
            report_date AS report_date,
            coalesce(primary_document, '') AS primary_document,
            CASE
                WHEN primary_document IS NOT NULL AND primary_document != '' THEN primary_document
                ELSE accession_number || '.txt'
            END AS document_path,
            CASE
                WHEN primary_document IS NOT NULL AND primary_document != '' THEN 'primary_document'
                ELSE 'submission_bundle'
            END AS document_path_source,
            CASE
                WHEN archive_url IS NOT NULL AND archive_url != '' THEN archive_url
                ELSE 'https://www.sec.gov/Archives/edgar/data/' || ltrim(source_cik, '0') || '/' || replace(accession_number, '-', '') || '/' || (
                    CASE WHEN primary_document IS NOT NULL AND primary_document != '' THEN primary_document ELSE accession_number || '.txt' END
                )
            END AS archive_url,
            coalesce(size, 0) AS reported_size,
            coalesce(is_xbrl, false) AS is_xbrl,
            coalesce(is_inline_xbrl, false) AS is_inline_xbrl,
            coalesce(is_xbrl_numeric, false) AS is_xbrl_numeric
        FROM raw_unnest
        WHERE form IS NOT NULL AND accession_number IS NOT NULL
    )
    SELECT
        sha256(source_cik || ':' || accession || ':' || document_path) AS occurrence_id,
        sha256(accession || ':' || document_path) AS document_locator_key,
        source_cik,
        accession,
        form,
        is_amendment,
        filing_date,
        report_date,
        primary_document,
        document_path,
        archive_url,
        document_path_source,
        reported_size,
        is_xbrl,
        is_inline_xbrl,
        is_xbrl_numeric
    FROM with_derived
    ORDER BY source_cik, accession, document_path
    """


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


__all__ = [
    "build_part_unnest_query",
    "build_profile_query",
]
