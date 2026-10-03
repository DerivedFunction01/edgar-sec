"""DuckDB SQL for filing-catalog materialization.

The derivation rules encoded here are the executable form of the section 3.3
table in ``roadmap/refactor_v2/phase_2.md`` and are the counterpart to the
Milestone 0 oracle, which transcribes the same rules in plain Python. The two
must agree; when they diverge, one of them is wrong and the test says which.

Two deliberate departures from the v1 SQL, both narrowing behaviour:

* ``trim`` is applied before the primary-document branch. v1 tested
  ``primary_document != ''``, so a whitespace-only value counted as a real
  document and produced a literal path of spaces. The Phase 1 engine
  (``build_archive_url``) already strips and treats such a value as missing,
  so v1 could emit a ``document_path_source`` that contradicted the ``archive_url``
  on the same row. v2 aligns the SQL with the engine.
* File paths are emitted as escaped SQL literals rather than interpolated
  raw, so a path containing a quote cannot terminate the string.
"""

from __future__ import annotations

from edgar_sec.domain.filing_catalog.schemas import (
    PATH_SOURCE_BUNDLE,
    PATH_SOURCE_PRIMARY,
    PROFILE_COLUMNS,
    PROFILE_SCHEMA_VERSION,
)
from edgar_sec.domain.sec_urls import SEC_ARCHIVE_BASE
from edgar_sec.infra.storage.duckdb import sql_identifier, sql_literal


def build_part_unnest_query(part_path: str) -> str:
    """Unnest one Phase 1 part into flat filing-occurrence rows.

    Exactly one source part per query. The materializer walks the snapshot's
    ordered parts and writes one shard per part, which is what keeps peak memory
    proportional to a part rather than to the whole cohort.

    Two properties of the SQL are load-bearing and must not be "simplified":

    * The unnest is **uncorrelated** — ``UNNEST(filings)`` in the select list of a
      subquery over the file. The correlated spelling
      (``FROM read_parquet(...) AS t, LATERAL (SELECT UNNEST(t.filings))``) is
      rewritten by DuckDB into a delim join, whose ``DELIM_SCAN`` must materialize
      the whole nested ``filings`` value for every source row before it can emit
      anything. That is an unspillable pin proportional to the entire part set, and
      it exhausts the memory limit on a part list that streams fine when unnested
      this way. ``tests/pipelines/filing_catalog/test_materialization.py`` pins the
      absence of a delim join in the plan.
    * Deduplication is **per source part**. ``occurrence_id`` is keyed on
      ``source_cik``, and the catalog guard requires each CIK to appear in exactly
      one source part, so the window below cannot miss a duplicate that lives in a
      different part.
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
    """Project deduplicated registrant profiles from a Phase 1 relation.

    The dedup window keeps the most recent ``fetched_at`` per CIK, which is what
    lets a later re-fetch of an already-seeded registrant supersede the earlier
    row without a second profile.
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


__all__ = [
    "build_part_unnest_query",
    "build_profile_query",
]
