"""SQL for document snapshot assembly and consolidation.

Only ``relation_for_parts`` output, literals in this file, and bound parameters reach
a statement — never a manifest or row value.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from typing import Any

from edgar_sec.infra.storage.duckdb import sql_path_list

#: Rows per fetched batch. Bounded so a consolidation never materializes a whole
#: quarter's text in memory at once.
DEFAULT_BATCH_SIZE = 4096
#: Env-overridable as ``documents.read_batch_size``.


def query_sql_batches(
    connection: Any,
    query: str,
    parameters: Sequence[Any] = (),
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> Iterator[list[dict[str, Any]]]:
    """Run a query and yield its rows in bounded batches, never materializing all."""
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    # ``connection.execute`` returns the *connection* in DuckDB, so closing what it
    # returns would close the caller's connection. A real cursor is required.
    cursor = connection.cursor()
    try:
        cursor.execute(query, tuple(parameters))
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                return
            columns = [description[0] for description in cursor.description]
            yield [dict(zip(columns, row, strict=True)) for row in rows]
    finally:
        cursor.close()


def ranked_union_relations(relations: Iterable[str]) -> str:
    """Union relations, tagging each with its input position as descending precedence.

    So the outcome depends only on the order the caller listed its sources.
    """
    values = [
        f"SELECT *, {rank} AS _snapshot_rank FROM {relation}"
        for rank, relation in enumerate(relations)
    ]
    if not values:
        raise ValueError("at least one relation is required")
    return "(" + " UNION ALL ".join(values) + ")"


def effective_snapshot_relations(
    index_relation: str, payload_relation: str
) -> tuple[str, str]:
    """Return deduplicated index and payload relations for layered snapshots.

    Highest ``_snapshot_rank`` wins; quarters are derived here, so old and new
    snapshots need no migration. An absent or out-of-range month buckets as 0/``QTR0``.
    """
    effective_index = f"""
        SELECT occurrence_id, source_cik, accession, form, filing_date,
               report_date, document_path, doc_id, mime_type, byte_size,
               payload_file,
               CASE WHEN length(filing_date) >= 4
                    THEN CAST(substr(filing_date, 1, 4) AS INTEGER)
                    ELSE 0
               END AS filing_year,
               CASE WHEN length(filing_date) >= 7
                     AND CAST(substr(filing_date, 6, 2) AS INTEGER) BETWEEN 1 AND 12
                    THEN 'QTR' || CAST(
                        floor((CAST(substr(filing_date, 6, 2) AS INTEGER) - 1) / 3) + 1
                        AS INTEGER
                    )
                    ELSE 'QTR0'
               END AS filing_quarter
        FROM (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY occurrence_id ORDER BY _snapshot_rank DESC
            ) AS _occurrence_rank
            FROM {index_relation}
        ) AS ranked_index
        WHERE _occurrence_rank = 1
    """
    effective_payload = f"""
        SELECT doc_id, clean_text
        FROM (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY doc_id ORDER BY _snapshot_rank DESC
            ) AS _payload_rank
            FROM {payload_relation}
        ) AS ranked_payload
        WHERE _payload_rank = 1
    """
    return effective_index, effective_payload


def relation_key_rows(
    connection: Any,
    relation: str,
    columns: Sequence[str],
    *,
    key_column: str,
    keys: Sequence[Any],
    batch_size: int,
) -> Iterator[list[dict[str, Any]]]:
    """Read rows matching a bounded key set from a relation."""
    if not keys:
        return
    projection = ", ".join(columns)
    placeholders = ",".join("?" for _ in keys)
    query = f"""
        SELECT {projection}
        FROM {relation} AS source_relation
        WHERE {key_column} IN ({placeholders})
    """
    yield from query_sql_batches(connection, query, tuple(keys), batch_size=batch_size)


def relation_payload_conflicts(
    connection: Any,
    relation: str,
    *,
    batch_size: int = 100,
) -> Iterator[list[dict[str, Any]]]:
    """Yield doc_ids whose normalized text differs across sources.

    Runs on the *raw* union: a differing text is refused, not resolved by precedence.
    """
    query = f"""
        SELECT doc_id
        FROM ({relation}) AS effective_payload
        GROUP BY doc_id
        HAVING count(DISTINCT sha256(clean_text)) > 1
    """
    yield from query_sql_batches(connection, query, batch_size=batch_size)


def relation_group_keys(
    connection: Any,
    relation: str,
    *,
    columns: Sequence[str],
    batch_size: int = 256,
) -> Iterator[list[dict[str, Any]]]:
    """Yield the distinct key combinations present in a relation."""
    selected = ", ".join(columns)
    query = f"""
        SELECT {selected}
        FROM ({relation}) AS grouped_relation
        GROUP BY {selected}
        ORDER BY {selected}
    """
    yield from query_sql_batches(connection, query, batch_size=batch_size)


def effective_quarter_batches(
    connection: Any,
    index_relation: str,
    payload_relation: str,
    *,
    year: int,
    quarter: str,
    batch_size: int,
    doc_lo: str | None = None,
    doc_hi: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    """Stream joined index and payload rows for one quarter, doc-range bounded."""
    bounds = ""
    parameters: list[Any] = [year, quarter]
    if doc_lo is not None and doc_hi is not None:
        bounds = " AND i.doc_id BETWEEN ? AND ?"
        parameters.extend([doc_lo, doc_hi])
    query = f"""
        SELECT i.occurrence_id, i.source_cik, i.accession, i.form,
               i.filing_date, i.report_date, i.document_path, i.doc_id,
               i.mime_type, i.byte_size, p.clean_text
        FROM ({index_relation}) AS i
        INNER JOIN ({payload_relation}) AS p ON p.doc_id = i.doc_id
        WHERE i.filing_year = ? AND i.filing_quarter = ?{bounds}
        ORDER BY i.doc_id
    """
    yield from query_sql_batches(
        connection, query, tuple(parameters), batch_size=batch_size
    )


def effective_quarter_index_rows(
    connection: Any,
    index_relation: str,
    *,
    year: int,
    quarter: str,
    batch_size: int,
) -> Iterator[list[dict[str, Any]]]:
    """Stream metadata-only index rows for one quarter, without payload joins."""
    query = f"""
        SELECT occurrence_id, source_cik, accession, form, filing_date,
               report_date, document_path, doc_id, mime_type, byte_size,
               payload_file
        FROM ({index_relation}) AS effective_index
        WHERE filing_year = ? AND filing_quarter = ?
        ORDER BY doc_id, occurrence_id
    """
    yield from query_sql_batches(
        connection, query, (year, quarter), batch_size=batch_size
    )


def chunk_assembly_query(chunk_paths: Sequence[str]) -> str:
    """Return the query concatenating chunk checkpoints into one sorted snapshot.

    ``ORDER BY`` is an artifact contract: a snapshot is read back by streaming.
    """
    if not chunk_paths:
        raise ValueError("assembly requires at least one chunk checkpoint")
    return f"""
        SELECT * FROM read_parquet({sql_path_list([str(path) for path in chunk_paths])})
        ORDER BY source_cik, accession
    """


__all__ = [
    "DEFAULT_BATCH_SIZE",
    "chunk_assembly_query",
    "effective_quarter_batches",
    "effective_quarter_index_rows",
    "effective_snapshot_relations",
    "query_sql_batches",
    "ranked_union_relations",
    "relation_group_keys",
    "relation_key_rows",
    "relation_payload_conflicts",
]
