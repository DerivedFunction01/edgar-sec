"""DuckDB staging stages for catalog-plan projection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.infra.storage.duckdb import sql_literal, sql_path_list
from edgar_sec.pipelines.document_inventory.cohort import CohortInputError
from edgar_sec.pipelines.document_inventory.snapshot.errors import BaseSnapshotError

__all__ = [
    "build_work_candidates",
    "check_metadata_against_base",
    "normalize_observations",
    "stage_base_accessions",
    "stage_cohort_tables",
    "stage_plan_targets",
]


def _projection_sql(parts: list[tuple[str, Path, int, str]]) -> str:
    selects = [
        f"SELECT document_locator_key, source_cik, accession, form, filing_date, "
        f"report_date, is_xbrl, is_inline_xbrl, primary_document, archive_url, "
        f"{sql_literal(form)} AS _expected_form "
        f"FROM read_parquet({sql_literal(str(path))}, hive_partitioning=false)"
        for form, path, _count, _digest in parts
    ]
    if not selects:
        return """CREATE TEMP TABLE raw_targets AS
            SELECT NULL::VARCHAR AS document_locator_key, NULL::VARCHAR AS accession,
                   NULL::VARCHAR AS source_cik, NULL::VARCHAR AS form, NULL::BOOLEAN AS is_xbrl,
                   NULL::VARCHAR AS filing_date, NULL::VARCHAR AS report_date,
                   NULL::BOOLEAN AS is_inline_xbrl, NULL::VARCHAR AS primary_document,
                   NULL::VARCHAR AS archive_url, NULL::VARCHAR AS _expected_form
            WHERE FALSE"""
    return "CREATE TEMP TABLE raw_targets AS " + " UNION ALL BY NAME ".join(selects)


def stage_plan_targets(
    connection: Any,
    parts: list[tuple[str, Path, int, str]],
    plan: dict[str, Any],
    locator_path: Path,
) -> None:
    connection.execute(_projection_sql(parts))
    target_rows = connection.execute("SELECT count(*) FROM raw_targets").fetchone()[0]
    if target_rows != plan["selected_rows"]:
        raise CohortInputError(
            "invalid_bundle", detail="read target row count differs from the plan"
        )
    bad_rows = connection.execute(
        """
            SELECT count(*) FROM raw_targets
            WHERE document_locator_key IS NULL OR trim(document_locator_key) = ''
               OR accession IS NULL OR source_cik IS NULL OR form IS NULL
               OR filing_date IS NULL
               OR (report_date IS NOT NULL AND trim(report_date) <> ''
                   AND try_cast(trim(report_date) AS DATE) IS NULL)
               OR trim(form) = '' OR trim(form) <> _expected_form
               OR NOT regexp_matches(trim(accession), '^[0-9]{10}-[0-9]{2}-[0-9]{6}$|^[0-9]{18}$')
               OR NOT regexp_matches(trim(source_cik), '^[0-9]+$')
               OR length(trim(source_cik)) > 10
               OR try_cast(trim(source_cik) AS BIGINT) > 9999999999
               OR try_cast(trim(filing_date) AS DATE) IS NULL
            """
    ).fetchone()[0]
    if bad_rows:
        raise CohortInputError(
            "invalid_bundle", detail=f"target plan has {bad_rows} invalid rows"
        )
    connection.execute(
        f"CREATE TEMP TABLE plan_locator_keys AS SELECT document_locator_key "
        f"FROM read_parquet({sql_literal(str(locator_path))})"
    )
    duplicate_locator = connection.execute(
        """
            SELECT document_locator_key FROM plan_locator_keys
            GROUP BY document_locator_key HAVING count(*) > 1 LIMIT 1
            """
    ).fetchone()
    if duplicate_locator:
        raise CohortInputError(
            "invalid_bundle", detail="plan locator keys are not unique"
        )
    locator_difference = connection.execute(
        """
            SELECT 1
            FROM (SELECT DISTINCT document_locator_key FROM raw_targets) target
            WHERE NOT EXISTS (
                SELECT 1 FROM plan_locator_keys locator
                WHERE locator.document_locator_key = target.document_locator_key
            )
            UNION ALL
            SELECT 1 FROM plan_locator_keys locator
            WHERE NOT EXISTS (
                SELECT 1 FROM raw_targets target
                WHERE target.document_locator_key = locator.document_locator_key
            )
            LIMIT 1
            """
    ).fetchone()
    if locator_difference:
        raise CohortInputError(
            "invalid_bundle",
            detail="target rows differ from published locator groups",
        )


def normalize_observations(connection: Any) -> None:
    connection.execute(
        """
            CREATE TEMP TABLE normalized_observations AS
            SELECT
                CASE
                    WHEN regexp_matches(trim(accession), '^[0-9]{18}$') THEN
                        substr(trim(accession), 1, 10) || '-' ||
                        substr(trim(accession), 11, 2) || '-' || substr(trim(accession), 13, 6)
                    ELSE trim(accession)
                END AS accession,
                lpad(cast(try_cast(trim(source_cik) AS BIGINT) AS VARCHAR), 10, '0') AS source_cik,
                trim(form) AS form,
                cast(try_cast(trim(filing_date) AS DATE) AS VARCHAR) AS filing_date,
                CASE
                    WHEN report_date IS NULL OR trim(report_date) = '' THEN NULL
                    ELSE cast(try_cast(trim(report_date) AS DATE) AS VARCHAR)
                END AS report_date,
                coalesce(is_xbrl, false) AS is_xbrl, coalesce(is_inline_xbrl, false) AS is_inline_xbrl,
                nullif(trim(coalesce(primary_document, '')), '') AS primary_document,
                nullif(trim(coalesce(archive_url, '')), '') AS archive_url
            FROM raw_targets
            """
    )
    duplicate_conflict = connection.execute(
        """
            SELECT accession, source_cik,
                   count(DISTINCT form) AS forms,
                   count(DISTINCT filing_date) AS filing_dates,
                   count(DISTINCT coalesce(report_date, '<null>')) AS report_dates
            FROM normalized_observations
            GROUP BY accession, source_cik
            HAVING forms > 1 OR filing_dates > 1 OR report_dates > 1
            LIMIT 1
            """
    ).fetchone()
    if duplicate_conflict:
        accession = AccessionNumber.from_any(duplicate_conflict[0])
        if duplicate_conflict[2] > 1:
            code = "conflicting_form"
            detail = "conflicting form values for duplicate source observation"
        elif duplicate_conflict[3] > 1:
            code = "conflicting_filing_date"
            detail = "conflicting filing dates for duplicate source observation"
        else:
            code = "conflicting_report_date"
            detail = "conflicting report dates for duplicate source observation"
        raise CohortInputError(
            code,
            accession,
            detail=f"{detail} (CIK {duplicate_conflict[1]})",
        )
    accession_conflict = connection.execute(
        """
            SELECT accession,
                   count(DISTINCT form) AS forms,
                   count(DISTINCT filing_date) AS filing_dates,
                   count(DISTINCT report_date) AS report_dates
            FROM normalized_observations
            GROUP BY accession
            HAVING forms > 1 OR filing_dates > 1 OR report_dates > 1
            LIMIT 1
            """
    ).fetchone()
    if accession_conflict:
        accession = AccessionNumber.from_any(accession_conflict[0])
        if accession_conflict[1] > 1:
            code = "conflicting_form"
        elif accession_conflict[2] > 1:
            code = "conflicting_filing_date"
        else:
            code = "conflicting_report_date"
        raise CohortInputError(code, accession)


def stage_cohort_tables(connection: Any) -> None:
    connection.execute(
        """
            CREATE TEMP TABLE cohort_accessions AS
            SELECT accession,
                   substr(replace(accession, '-', ''), 1, 10) AS filing_cik,
                   min(form) AS form,
                   min(filing_date) AS filing_date,
                   max(report_date) AS report_date
            FROM normalized_observations
            GROUP BY accession
            """
    )
    connection.execute(
        """
            CREATE TEMP TABLE cohort_sources AS
            SELECT DISTINCT accession, source_cik
            FROM normalized_observations
            """
    )
    connection.execute(
        """
            CREATE TEMP TABLE cohort_archive_ciks AS
            SELECT accession, min(source_cik) AS archive_cik
            FROM cohort_sources
            GROUP BY accession
            """
    )


def stage_base_accessions(
    connection: Any, base_parts: list[tuple[Path, int, str]]
) -> None:
    base_files = [str(path) for path, _count, _digest in base_parts]
    if base_files:
        connection.execute(
            f"CREATE TEMP TABLE base_accessions AS SELECT accession, filing_cik, form, filing_date, report_date "
            f"FROM read_parquet({sql_path_list(base_files)})"
        )
    else:
        connection.execute(
            """
                CREATE TEMP TABLE base_accessions (
                    accession VARCHAR, filing_cik VARCHAR, form VARCHAR,
                    filing_date VARCHAR, report_date VARCHAR
                )
                """
        )
    base_row_count = connection.execute(
        "SELECT count(*) FROM base_accessions"
    ).fetchone()[0]
    if base_row_count != sum(count for _path, count, _digest in base_parts):
        raise BaseSnapshotError(
            "base snapshot accession row count changed while reading"
        )
    invalid_base = connection.execute(
        """
            SELECT accession
            FROM base_accessions
            WHERE accession IS NULL
               OR NOT regexp_matches(accession, '^[0-9]{10}-[0-9]{2}-[0-9]{6}$')
               OR filing_cik IS NULL
               OR NOT regexp_matches(filing_cik, '^[0-9]{10}$')
               OR filing_cik <> substr(replace(accession, '-', ''), 1, 10)
               OR form IS NULL OR trim(form) = '' OR trim(form) <> form
               OR try_cast(filing_date AS DATE) IS NULL
               OR strftime(try_cast(filing_date AS DATE), '%Y-%m-%d') <> filing_date
               OR (report_date IS NOT NULL AND (
                   try_cast(report_date AS DATE) IS NULL
                   OR strftime(try_cast(report_date AS DATE), '%Y-%m-%d') <> report_date
               ))
            LIMIT 1
            """
    ).fetchone()
    if invalid_base:
        raise BaseSnapshotError("base snapshot contains invalid accession facts")
    duplicate_base = connection.execute(
        "SELECT accession FROM base_accessions GROUP BY accession HAVING count(*) > 1 LIMIT 1"
    ).fetchone()
    if duplicate_base:
        raise BaseSnapshotError(
            f"base snapshot has duplicate accession {duplicate_base[0]}"
        )


def check_metadata_against_base(connection: Any) -> None:
    metadata_mismatch = connection.execute(
        """
            SELECT c.accession
            FROM cohort_accessions c
            JOIN base_accessions b USING (accession)
            WHERE c.form <> b.form OR c.filing_date <> b.filing_date
               OR (c.report_date IS NOT NULL AND b.report_date IS NOT NULL
                   AND c.report_date <> b.report_date)
            LIMIT 1
            """
    ).fetchone()
    if metadata_mismatch:
        raise CohortInputError(
            "invalid_bundle",
            AccessionNumber.from_any(metadata_mismatch[0]),
            detail="filing metadata conflicts with the base snapshot",
        )


def build_work_candidates(
    connection: Any, *, archive_base_url: str, explicit_refresh: bool
) -> str:
    base_url = archive_base_url.rstrip("/")
    connection.execute(
        f"""
            CREATE TEMP TABLE cohort_accessions_with_url AS
            SELECT facts.accession, facts.filing_cik, facts.form,
                   facts.filing_date, facts.report_date,
                   {sql_literal(base_url)} || '/' ||
                   cast(try_cast(route.archive_cik AS BIGINT) AS VARCHAR) || '/' ||
                   replace(facts.accession, '-', '') || '/' || facts.accession || '-index.html' AS index_url
            FROM cohort_accessions facts
            JOIN cohort_archive_ciks route USING (accession)
            """
    )
    connection.execute(
        """
            CREATE TEMP TABLE work_candidates AS
            SELECT c.accession, c.index_url, c.form, CASE WHEN r.flagged THEN 'summary' ELSE 'index' END AS vehicle,
                   route.archive_cik, r.primary_document, r.is_inline_xbrl
            FROM cohort_accessions_with_url c
            JOIN cohort_archive_ciks route USING (accession)
            JOIN (SELECT accession, bool_or(is_xbrl) AS flagged, bool_or(is_inline_xbrl) AS is_inline_xbrl,
                         min(primary_document) AS primary_document
                  FROM normalized_observations GROUP BY accession) r USING (accession)
            LEFT JOIN base_accessions b USING (accession)
            WHERE ? OR b.accession IS NULL
            """,
        [explicit_refresh],
    )
    return base_url
