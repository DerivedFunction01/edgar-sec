"""DuckDB SQL construction for filing-catalog materialization.

The derivation rules encoded here are the executable form of the section 3.3
table in ``roadmap/refactor_v2/phase_2.md`` and are the counterpart to the
Milestone 0 oracle, which transcribes the same rules in plain Python. The two
must agree; when they diverge, one of them is wrong and the test says which.

Two deliberate departures from the v1 SQL, both narrowing behaviour:

* ``trim`` is applied before the primary-document branch. v1 tested
  ``primary_document != ''``, so a whitespace-only value counted as a real
  document and produced a literal path of spaces. The Phase 1 engine
  (``build_archive_url``) already strips and treats such a value as missing, so
  v1 could emit a ``document_path_source`` that contradicted the ``archive_url``
  on the same row. v2 aligns the SQL with the engine.
* File paths are emitted as escaped SQL literals rather than interpolated
  raw, so a path containing a quote cannot terminate the string.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from pathlib import Path

from edgar_sec.domain.filing_catalog.filters import (
    GRANULARITY_QUARTER,
    AbsoluteDateClause,
    DateSelection,
    RecurringDateClause,
)
from edgar_sec.domain.filing_catalog.schemas import (
    PATH_SOURCE_BUNDLE,
    PATH_SOURCE_PRIMARY,
    PROFILE_COLUMNS,
    PROFILE_SCHEMA_VERSION,
)
from edgar_sec.domain.sec_urls import SEC_ARCHIVE_BASE
from edgar_sec.infra.storage.parquet import (
    DEFAULT_COMPRESSION,
    DEFAULT_ROW_GROUP_SIZE,
    count_parquet_rows,
)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# The alias a date predicate filters on. It is a module constant rather than a
# caller argument so the projection fragment and the predicate cannot drift
# apart, and so a caller that wraps a relation knows the extra column to project
# away.
PARSED_DATE_ALIAS = "parsed_report_date"


def sql_literal(value: str) -> str:
    """Return ``value`` as a single-quoted SQL string literal.

    Embedded single quotes are doubled, which is the SQL-standard escape. Path
    segments reaching this function are already constrained to
    ``[A-Za-z0-9_.-]`` by the path resolver, so this is defence in depth rather
    than the primary control.
    """
    return "'" + str(value).replace("'", "''") + "'"


def sql_path_list(paths: Sequence[str]) -> str:
    """Return ``paths`` as a SQL list literal for ``read_parquet([...])``.

    A snapshot is a dataset, so a consumer may need to read several parts. The
    list is built element by element with :func:`sql_literal` rather than by
    joining a string, so a path cannot break out of its own element.
    """
    return "[" + ", ".join(sql_literal(str(path)) for path in paths) + "]"


def _qualified_identifier(name: str) -> str:
    """Return ``name`` if it is a dotted path of bare SQL identifiers, else raise.

    Relation names are passed through here so a catalog or table name can never
    smuggle SQL into a query. An optional ``alias.`` prefix is accepted because
    a predicate built once and reused inside a joined query still has to name
    the column it filters on; each segment is validated independently, so the
    allowance cannot become a hole.
    """
    if not name or not all(
        _IDENTIFIER_RE.match(segment) for segment in name.split(".")
    ):
        raise ValueError(f"unsafe SQL identifier: {name!r}")
    return name


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
      this way. ``tests/infra/storage/test_duckdb_catalog.py`` pins the absence of
      a delim join in the plan.
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
    source = _qualified_identifier(relation)
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


def copy_query_to_parquet(
    con: object,
    query: str,
    destination: os.PathLike[str] | str,
    row_group_size: int = DEFAULT_ROW_GROUP_SIZE,
    *,
    compression: str = DEFAULT_COMPRESSION,
) -> int:
    """Write one query result to Parquet out-of-core and atomically.

    The COPY runs inside DuckDB, so a large result never materializes in the
    Python heap. The file is staged beside its destination and renamed, so a
    failed write never leaves a half-written shard in a published directory.
    Returns the row count.
    """
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    try:
        con.execute(
            f"COPY ({query}) TO {sql_literal(str(tmp))} "
            f"(FORMAT PARQUET, COMPRESSION {compression}, "
            f"ROW_GROUP_SIZE {int(row_group_size)})"
        )
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return count_parquet_rows(path)


def suffix_sql(column: str, suffixes: tuple[str, ...]) -> str:
    """Return a SQL predicate matching ``column`` against any allowed suffix.

    An empty suffix tuple yields ``TRUE`` so a caller can always apply the
    predicate unconditionally. A non-empty one is parenthesized: the predicate
    is a disjunction, and a caller that conjoins it with ``AND`` without
    adding its own parentheses would silently change the meaning to
    ``a AND b OR c``.
    """
    _qualified_identifier(column)
    if not suffixes:
        return "TRUE"
    return (
        "("
        + " OR ".join(
            f"lower({column}) LIKE {sql_literal('%.' + suffix)}" for suffix in suffixes
        )
        + ")"
    )


def date_projection_sql(column: str) -> str:
    """Return the projection fragment that parses a text date column once.

    ``report_date`` is stored as text, so any date predicate has to parse it.
    Emitting the parse inline instead costs a re-parse per reference: over the
    3.19M rows of a published catalog, the same four-clause selection measured
    0.36s inline against 0.11s projected once, with nine ``TRY_CAST`` nodes in
    the inline plan against none in the projected one. The fragment therefore
    names one alias, and :func:`date_selection_sql` filters on it.

    The alias is an extra column, so a caller projecting ``SELECT *`` will leak
    it into the result. A published catalog shard has a fixed schema, so the
    caller must project its own columns out of the wrapped relation.
    """
    return f"TRY_CAST({_qualified_identifier(column)} AS DATE) AS {PARSED_DATE_ALIAS}"


def parsed_date_relation(source_sql: str, column: str) -> str:
    """Wrap ``source_sql`` so a date predicate sees exactly one parsed column.

    Both callers that filter a date need the same shape -- deterministic
    planning over the catalog, and the selection engine over its feature
    snapshot -- so the wrapping lives here rather than being written twice. The
    relation is aliased by the caller's own query, which is why the projection
    stays inside: the alias is visible to the enclosing ``WHERE`` without the
    caller's qualified column references seeing a new name.
    """
    return f"(SELECT *, {date_projection_sql(column)} FROM {source_sql})"


def date_selection_sql(selection: DateSelection) -> str:
    """Return the predicate matching a parsed ``report_date`` against ``selection``.

    The predicate takes the alias :func:`date_projection_sql` defines rather
    than the raw column, because a recurring clause needs the parsed value twice
    (period and year) and an OR of several clauses needs it many more times.

    An empty selection is ``TRUE``, matching the other predicate builders: no
    date predicate at all, which keeps rows whose ``report_date`` is missing.
    A nonempty selection cannot represent those rows -- a missing date has no
    quarter and no interval -- so it excludes them, which is why the two answers
    differ rather than being two spellings of one.
    """
    if not selection:
        return "TRUE"
    column = PARSED_DATE_ALIAS
    parts = [
        _recurring_clause_sql(column, clause)
        if isinstance(clause, RecurringDateClause)
        else _absolute_clause_sql(column, clause)
        for clause in selection
    ]
    if len(parts) == 1:
        return parts[0]
    return "(" + " OR ".join(parts) + ")"


def _absolute_clause_sql(column: str, clause: AbsoluteDateClause) -> str:
    """Emit one interval.

    No parentheses: a comparison or ``BETWEEN`` is an atom, and ``BETWEEN``'s
    ``AND`` binds tighter than any ``AND`` a caller conjoins with it, so this
    cannot swallow a neighbouring condition the way a bare conjunction would.
    """
    if clause.start_date is not None and clause.end_date is not None:
        return (
            f"{column} BETWEEN DATE '{clause.start_date.isoformat()}' "
            f"AND DATE '{clause.end_date.isoformat()}'"
        )
    if clause.start_date is not None:
        return f"{column} >= DATE '{clause.start_date.isoformat()}'"
    return f"{column} <= DATE '{clause.end_date.isoformat()}'"


def _recurring_clause_sql(column: str, clause: RecurringDateClause) -> str:
    """Emit one recurring clause, parenthesized because it is a conjunction."""
    part = "quarter" if clause.granularity == GRANULARITY_QUARTER else "month"
    values = ", ".join(str(value) for value in clause.values)
    checks = [f"date_part('{part}', {column}) IN ({values})"]
    if clause.start_year is not None:
        checks.append(f"date_part('year', {column}) >= {int(clause.start_year)}")
    if clause.end_year is not None:
        checks.append(f"date_part('year', {column}) <= {int(clause.end_year)}")
    return "(" + " AND ".join(checks) + ")"


__all__ = [
    "PARSED_DATE_ALIAS",
    "build_part_unnest_query",
    "build_profile_query",
    "copy_query_to_parquet",
    "date_projection_sql",
    "date_selection_sql",
    "parsed_date_relation",
    "sql_literal",
    "sql_path_list",
    "suffix_sql",
]
