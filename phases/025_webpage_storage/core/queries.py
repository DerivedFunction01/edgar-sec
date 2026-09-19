"""Phase 2.5 DuckDB relation operations for webpage storage.

These functions hardcode SEC filing-specific column names and layered
snapshot logic. They are phase-specific, not generic storage primitives.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from typing import Any


def ranked_union_relations(relations: Iterable[str]) -> str:
    """Union relations while retaining deterministic source precedence."""
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
    """Return deduplicated index/payload relations for layered snapshots."""
    effective_index = f"""
        SELECT occurrence_id, source_cik, accession, form, filing_date,
               report_date, document_path, doc_id, mime_type, byte_size,
               payload_file,
               CAST(substr(filing_date, 1, 4) AS INTEGER) AS filing_year,
               'QTR' || CAST(
                   floor((CAST(substr(filing_date, 6, 2) AS INTEGER) - 1) / 3) + 1
                   AS INTEGER
               ) AS filing_quarter
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
    executor,
    relation: str,
    columns: Sequence[str],
    *,
    key_column: str,
    keys: Sequence[Any],
    batch_size: int,
) -> Iterator[list[dict[str, Any]]]:
    """Read rows matching a bounded key set from a relation."""
    if not keys:
        return iter(())
    projection = ", ".join(columns)
    placeholders = ",".join("?" for _ in keys)
    query = f"""
        SELECT {projection}
        FROM {relation} AS source_relation
        WHERE {key_column} IN ({placeholders})
    """
    return executor.query_sql_batches(query, tuple(keys), batch_size=batch_size)


def relation_payload_conflicts(
    executor, relation: str, *, batch_size: int = 100
) -> Iterator[list[dict[str, Any]]]:
    query = f"""
        SELECT doc_id
        FROM ({relation}) AS effective_payload
        GROUP BY doc_id
        HAVING count(DISTINCT sha256(clean_text)) > 1
    """
    return executor.query_sql_batches(query, batch_size=batch_size)


def relation_group_keys(
    executor,
    relation: str,
    *,
    columns: Sequence[str],
    batch_size: int = 256,
) -> Iterator[list[dict[str, Any]]]:
    selected = ", ".join(columns)
    query = f"""
        SELECT {selected}
        FROM ({relation}) AS grouped_relation
        GROUP BY {selected}
        ORDER BY {selected}
    """
    return executor.query_sql_batches(query, batch_size=batch_size)


def effective_quarter_batches(
    executor,
    index_relation: str,
    payload_relation: str,
    *,
    year: int,
    quarter: str,
    batch_size: int,
    doc_lo: str | None = None,
    doc_hi: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    """Stream joined index/payload rows for one quarter, optionally doc-bounded."""
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
        ORDER BY i.occurrence_id
    """
    return executor.query_sql_batches(query, tuple(parameters), batch_size=batch_size)


def effective_quarter_index_rows(
    executor,
    index_relation: str,
    *,
    year: int,
    quarter: str,
    batch_size: int,
) -> Iterator[list[dict[str, Any]]]:
    """Stream metadata-only index rows for one quarter without payload joins."""
    query = f"""
        SELECT occurrence_id, source_cik, accession, form, filing_date,
               report_date, document_path, doc_id, mime_type, byte_size,
               payload_file
        FROM ({index_relation}) AS effective_index
        WHERE filing_year = ? AND filing_quarter = ?
        ORDER BY doc_id, occurrence_id
    """
    return executor.query_sql_batches(query, (year, quarter), batch_size=batch_size)


__all__ = [
    "effective_quarter_batches",
    "effective_quarter_index_rows",
    "effective_snapshot_relations",
    "ranked_union_relations",
    "relation_group_keys",
    "relation_key_rows",
    "relation_payload_conflicts",
]
