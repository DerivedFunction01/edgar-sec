"""Direct SQL for document snapshot consolidation.

Ported from v1's ``core/queries.py``. The functions build SQL text over DuckDB
relations; there is no query AST. v1 also emitted strings — the AST it used was
executor plumbing, not part of these functions — and v2 has no AST and no
SQL-boundary rule, so direct strings are the native form here.

Every statement in this module is assembled from three sources: a literal in
this file, a relation expression built by
:func:`edgar_sec.infra.storage.document_parts.relation_for_parts` (which quotes
and escapes its own file list), and bound parameters. No value read from a
manifest or a row is ever interpolated into a statement, which is what keeps a
hand-edited manifest from becoming SQL.

The functions hardcode SEC filing-specific column names and layered snapshot
logic. They are phase-specific, not generic storage primitives.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from typing import Any

#: Rows per fetched batch. Bounded so a consolidation never materializes a whole
#: quarter's text in memory at once.
DEFAULT_BATCH_SIZE = 4096
#: Registered as ``documents.read_batch_size`` in the settings registry, so the
#: value is env-overridable like every other batch size. This module is the
#: authority for the value; tests/pipelines/document_storage/test_settings_contract.py
#: pins the pair.


def query_sql_batches(
    connection: Any,
    query: str,
    parameters: Sequence[Any] = (),
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> Iterator[list[dict[str, Any]]]:
    """Run a query and yield its rows in bounded batches.

    The adapter for v1's ``SqlExecutor.query_sql_batches``. Uses ``fetchmany``
    rather than materializing the result, because the payload queries here carry
    full document text.
    """
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
    """Union relations while retaining deterministic source precedence.

    Each relation is tagged with its position in the input, and every downstream
    dedup ranks on that tag descending. Position therefore *is* precedence, so
    the result of a consolidation depends only on the order the caller listed
    its sources — not on filesystem or query ordering.
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

    The highest-precedence row per identity wins. ``filing_year`` and
    ``filing_quarter`` are derived here rather than stored, so a snapshot written
    by an older version consolidates alongside a newer one without a migration.

    The quarter derivation uses ``floor((month - 1) / 3) + 1``, matching how SEC
    fiscal quarters are numbered. Two degenerate cases are handled explicitly
    rather than left to ``CAST``:

    * A **missing or malformed** ``filing_date`` would make ``CAST(substr(...))``
      raise a conversion error and abort the whole consolidation. It is bucketed
      as year ``0`` / quarter ``QTR0`` instead.
    * A date with a month outside ``1-12`` would derive a quarter outside
      ``QTR1``-``QTR4``. It is also bucketed as ``QTR0``.

    Both are reportable states, so neither drops a document: every acquired
    document lands in exactly one bucket, and a corpus with undated documents
    consolidates into a visibly separate ``QTR0`` partition rather than
    disappearing. ``QTR0`` sorts before real quarters, so it is where a reviewer
    looks first.
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
    """Yield document ids whose normalized text differs across sources.

    Conflict detection runs on the *raw* union, not the deduplicated relation, on
    purpose: deduplication resolves precedence by silently discarding the losing
    row, and a consolidation that discards a different text for a document it
    already has is the one case worth refusing rather than resolving.
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


__all__ = [
    "DEFAULT_BATCH_SIZE",
    "effective_quarter_batches",
    "effective_quarter_index_rows",
    "effective_snapshot_relations",
    "query_sql_batches",
    "ranked_union_relations",
    "relation_group_keys",
    "relation_key_rows",
    "relation_payload_conflicts",
]
