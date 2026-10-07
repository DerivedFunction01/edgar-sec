"""DuckDB SQL for filing-catalog materialization.
``trim`` runs before the primary-document branch, so a whitespace-only value counts
as missing and cannot publish a ``document_path_source`` contradicting the
``archive_url`` beside it. Paths are escaped SQL literals, never interpolated raw.
"""

from __future__ import annotations

from collections.abc import Sequence

from edgar_sec.domain.filing_catalog.schemas import (
    PATH_SOURCE_BUNDLE,
    PATH_SOURCE_PRIMARY,
    PROFILE_COLUMNS,
    PROFILE_SCHEMA_VERSION,
)
from edgar_sec.domain.sec_urls import SEC_ARCHIVE_BASE
from edgar_sec.infra.storage.duckdb import sql_identifier, sql_literal, sql_path_list


def build_part_unnest_query(part_path: str) -> str:
    """Unnest one source part into flat filing-occurrence rows.
    Two properties must not be "simplified": the unnest is **uncorrelated**, since
    the correlated spelling pins the whole nested value; dedup is **per part**.
    """
    if not str(part_path):
        raise ValueError("build_part_unnest_query requires a source part")
    path = sql_literal(str(part_path))
    return f"""
    WITH raw_unnest AS (
        SELECT
            t.cik AS source_cik,
            f.form AS form,
            f.accession_number AS accession_number,
            f.filing_date AS filing_date,
            f.report_date AS report_date,
            f.primary_document AS primary_document,
            f.archive_url AS archive_url,
            f.size AS size,
            f.is_xbrl AS is_xbrl,
            f.is_inline_xbrl AS is_inline_xbrl,
            f.is_xbrl_numeric AS is_xbrl_numeric
        FROM (
            SELECT cik, UNNEST(filings) AS f
            FROM read_parquet({path})
        ) AS t
        WHERE t.f IS NOT NULL
    ),
    normalized AS (
        SELECT
            source_cik,
            form,
            accession_number,
            replace(accession_number, '-', '') AS accession,
            coalesce(nullif(trim(form), ''), '') AS form_clean,
            coalesce(nullif(trim(filing_date), ''), '') AS filing_date,
            coalesce(nullif(trim(report_date), ''), '') AS report_date,
            nullif(trim(primary_document), '') AS primary_document,
            coalesce(nullif(trim(archive_url), ''), '') AS archive_url,
            coalesce(size, 0) AS reported_size,
            coalesce(is_xbrl, false) AS is_xbrl,
            coalesce(is_inline_xbrl, false) AS is_inline_xbrl,
            coalesce(is_xbrl_numeric, false) AS is_xbrl_numeric
        FROM raw_unnest
    ),
    with_derived AS (
        SELECT
            source_cik,
            accession,
            form_clean AS form,
            filing_date,
            report_date,
            coalesce(primary_document, '') AS primary_document,
            CASE
                WHEN primary_document IS NOT NULL
                    THEN primary_document
                ELSE accession_number || '.txt'
            END AS document_path,
            CASE
                WHEN primary_document IS NOT NULL
                    THEN {sql_literal(PATH_SOURCE_PRIMARY)}
                ELSE {sql_literal(PATH_SOURCE_BUNDLE)}
            END AS document_path_source,
            CASE
                WHEN archive_url != ''
                    THEN archive_url
                ELSE {sql_literal(SEC_ARCHIVE_BASE)} || '/' ||
                     ltrim(source_cik, '0') || '/' || accession || '/' ||
                     CASE
                         WHEN primary_document IS NOT NULL
                             THEN primary_document
                         ELSE accession_number || '.txt'
                     END
            END AS archive_url,
            reported_size,
            is_xbrl,
            is_inline_xbrl,
            is_xbrl_numeric
        FROM normalized
        WHERE form IS NOT NULL AND accession_number IS NOT NULL
          AND accession_number != ''
    )
    SELECT
        sha256(source_cik || ':' || accession || ':' || document_path)
            AS occurrence_id,
        sha256(accession || ':' || document_path) AS document_locator_key,
        source_cik,
        accession,
        form,
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
    FROM (
        SELECT
            *,
            ROW_NUMBER() OVER (
                PARTITION BY sha256(
                    source_cik || ':' || accession || ':' || document_path
                )
                ORDER BY source_cik, accession, document_path, filing_date
            ) AS occurrence_rank
        FROM with_derived
    ) ranked
    WHERE occurrence_rank = 1
    ORDER BY source_cik, accession, document_path
    """


def build_profile_query(relation: str) -> str:
    """Project deduplicated registrant profiles from a source relation.
    The window keeps the most recent ``fetched_at`` per CIK, so a re-fetch supersedes
    the earlier row without a second profile.
    """
    source = sql_identifier(relation)
    profile_cols = ", ".join(f'"{name}"' for name in PROFILE_COLUMNS[:-1])
    return f"""
    SELECT
        {profile_cols},
        {sql_literal(PROFILE_SCHEMA_VERSION)} AS profile_schema_version
    FROM (
        SELECT *,
               ROW_NUMBER() OVER (
                   PARTITION BY cik
                   ORDER BY fetched_at DESC NULLS LAST
               ) AS rn
        FROM {source}
        WHERE cik IS NOT NULL
    ) ranked
    WHERE rn = 1
    ORDER BY cik
    """


def build_delta_unnest_query(part_path: str, base_target_paths: Sequence[str]) -> str:
    """Unnest one delta part into filing occurrences, excluding base occurrences."""
    if not base_target_paths:
        return build_part_unnest_query(part_path)
    if not str(part_path):
        raise ValueError("build_delta_unnest_query requires a source part")
    path = sql_literal(str(part_path))
    base_list = sql_path_list([str(p) for p in base_target_paths])
    return f"""
    WITH raw_unnest AS (
        SELECT
            t.cik AS source_cik,
            f.form AS form,
            f.accession_number AS accession_number,
            f.filing_date AS filing_date,
            f.report_date AS report_date,
            f.primary_document AS primary_document,
            f.archive_url AS archive_url,
            f.size AS size,
            f.is_xbrl AS is_xbrl,
            f.is_inline_xbrl AS is_inline_xbrl,
            f.is_xbrl_numeric AS is_xbrl_numeric
        FROM (
            SELECT cik, UNNEST(filings) AS f
            FROM read_parquet({path})
        ) AS t
        WHERE t.f IS NOT NULL
    ),
    normalized AS (
        SELECT
            source_cik,
            form,
            accession_number,
            replace(accession_number, '-', '') AS accession,
            coalesce(nullif(trim(form), ''), '') AS form_clean,
            coalesce(nullif(trim(filing_date), ''), '') AS filing_date,
            coalesce(nullif(trim(report_date), ''), '') AS report_date,
            nullif(trim(primary_document), '') AS primary_document,
            coalesce(nullif(trim(archive_url), ''), '') AS archive_url,
            coalesce(size, 0) AS reported_size,
            coalesce(is_xbrl, false) AS is_xbrl,
            coalesce(is_inline_xbrl, false) AS is_inline_xbrl,
            coalesce(is_xbrl_numeric, false) AS is_xbrl_numeric
        FROM raw_unnest
    ),
    with_derived AS (
        SELECT
            source_cik,
            accession,
            form_clean AS form,
            filing_date,
            report_date,
            coalesce(primary_document, '') AS primary_document,
            CASE
                WHEN primary_document IS NOT NULL
                    THEN primary_document
                ELSE accession_number || '.txt'
            END AS document_path,
            CASE
                WHEN primary_document IS NOT NULL
                    THEN {sql_literal(PATH_SOURCE_PRIMARY)}
                ELSE {sql_literal(PATH_SOURCE_BUNDLE)}
            END AS document_path_source,
            CASE
                WHEN archive_url != ''
                    THEN archive_url
                ELSE {sql_literal(SEC_ARCHIVE_BASE)} || '/' ||
                     ltrim(source_cik, '0') || '/' || accession || '/' ||
                     CASE
                         WHEN primary_document IS NOT NULL
                             THEN primary_document
                         ELSE accession_number || '.txt'
                     END
            END AS archive_url,
            reported_size,
            is_xbrl,
            is_inline_xbrl,
            is_xbrl_numeric
        FROM normalized
        WHERE form IS NOT NULL AND accession_number IS NOT NULL
          AND accession_number != ''
    ),
    candidates AS (
        SELECT
            sha256(source_cik || ':' || accession || ':' || document_path)
                AS occurrence_id,
            sha256(accession || ':' || document_path) AS document_locator_key,
            source_cik,
            accession,
            form,
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
        FROM (
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY sha256(
                        source_cik || ':' || accession || ':' || document_path
                    )
                    ORDER BY source_cik, accession, document_path, filing_date
                ) AS occurrence_rank
            FROM with_derived
        ) ranked
        WHERE occurrence_rank = 1
    )
    SELECT c.*
    FROM candidates c
    ANTI JOIN read_parquet({base_list}) b
      ON c.occurrence_id = b.occurrence_id
    ORDER BY c.source_cik, c.accession, c.document_path
    """


def build_delta_profile_query(delta_relation: str, base_profiles_path: str) -> str:
    """Project profiles combining base and delta, superseding by fetched_at."""
    delta_source = sql_identifier(delta_relation)
    base_source = sql_literal(base_profiles_path)
    profile_cols = ", ".join(f'"{name}"' for name in PROFILE_COLUMNS[:-1])
    return f"""
    WITH delta_profiles AS (
        SELECT
            {profile_cols},
            {sql_literal(PROFILE_SCHEMA_VERSION)} AS profile_schema_version,
            fetched_at
        FROM (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY cik
                       ORDER BY fetched_at DESC NULLS LAST
                   ) AS rn
            FROM {delta_source}
            WHERE cik IS NOT NULL
        ) ranked
        WHERE rn = 1
    ),
    combined AS (
        SELECT {profile_cols}, profile_schema_version, fetched_at
        FROM read_parquet({base_source})
        UNION ALL
        SELECT {profile_cols}, profile_schema_version, fetched_at
        FROM delta_profiles
    )
    SELECT
        {profile_cols},
        profile_schema_version
    FROM (
        SELECT *,
               ROW_NUMBER() OVER (
                   PARTITION BY cik
                   ORDER BY fetched_at DESC NULLS LAST
               ) AS rn
        FROM combined
    ) ranked
    WHERE rn = 1
    ORDER BY cik
    """


__all__ = [
    "build_delta_profile_query",
    "build_delta_unnest_query",
    "build_part_unnest_query",
    "build_profile_query",
]
