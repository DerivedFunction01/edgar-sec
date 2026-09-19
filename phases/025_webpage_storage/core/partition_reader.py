"""Bounded readers for normalized Phase 2.5 SQLite partitions."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, Self

from defs.sql import (
    BooleanGroup,
    Compare,
    ComparisonOp,
    Direction,
    Membership,
    OrderBy,
    Select,
    Table,
    ValueList,
    col,
    make_sql_executor,
    param,
)


def choose_normalized(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Choose one deterministic normalized artifact per source document."""
    chosen: dict[str, dict[str, Any]] = {}
    hashes: dict[str, set[str]] = {}
    fingerprints: dict[str, set[str]] = {}
    for row in rows:
        source_doc_id = str(row["source_doc_id"])
        hashes.setdefault(source_doc_id, set()).add(str(row["payload_sha256"]))
        fingerprints.setdefault(source_doc_id, set()).add(
            str(row.get("processor_fingerprint", ""))
        )
        key = (
            int(row.get("schema_version", 0)),
            str(row.get("processor_fingerprint", "")),
            str(row.get("normalized_artifact_id", "")),
        )
        prior = chosen.get(source_doc_id)
        if prior is None or key > prior["_selection_key"]:
            chosen[source_doc_id] = {**row, "_selection_key": key}
    conflicts = [
        doc_id
        for doc_id, values in hashes.items()
        if len(values) > 1 and len(fingerprints[doc_id]) == 1
    ]
    if conflicts:
        raise ValueError(
            "conflicting normalized payloads for doc_id(s): "
            + ", ".join(sorted(conflicts))
        )
    for row in chosen.values():
        row.pop("_selection_key", None)
    return chosen


class PartitionBatchReader:
    """Stream occurrence/normalized rows from one finalized partition.

    DuckDB performs the join and deterministic normalized-row selection over a
    read-only SQLite attachment. The iterator exposes only bounded result
    batches; compressed payloads are never accumulated in Python.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        threads: int | None = None,
        memory_limit: str | None = None,
        temp_directory: str | Path | None = None,
    ) -> None:
        self.path = Path(path).resolve()
        self.executor = make_sql_executor(
            self.path,
            dialect="duckdb",
            threads=threads,
            memory_limit=memory_limit,
            temp_directory=temp_directory,
        )
        self._closed = False

    def iter_rows(
        self,
        *,
        batch_size: int = 512,
        include_missing: bool = False,
        with_payload: bool = True,
    ) -> Iterator[list[dict[str, Any]]]:
        """Yield deterministic batches containing one selected normalized row.

        With ``with_payload=False`` the compressed blob column is excluded from
        the projection so metadata-only planning passes can read very large
        batches without touching blob pages.
        """
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        last_doc_id: str | None = None
        last_occurrence_id: str | None = None
        occurrence_columns = OCCURRENCE_COLUMNS
        normalized_columns = _normalized_columns(with_payload)
        while True:
            keyset = None
            if last_doc_id is not None and last_occurrence_id is not None:
                keyset = BooleanGroup.or_(
                    Compare(col("doc_id"), ComparisonOp.GT, param(last_doc_id)),
                    BooleanGroup.and_(
                        Compare(col("doc_id"), ComparisonOp.EQ, param(last_doc_id)),
                        Compare(
                            col("occurrence_id"),
                            ComparisonOp.GT,
                            param(last_occurrence_id),
                        ),
                    ),
                )
            occurrence_query = Select(
                source=Table("filing_occurrences"),
                projection=tuple(col(column) for column in occurrence_columns),
                where=keyset,
                order_by=(
                    OrderBy(col("doc_id"), Direction.ASC),
                    OrderBy(col("occurrence_id"), Direction.ASC),
                ),
                limit=batch_size,
            )
            occurrence_batches = self.executor.query_batches(
                self.executor.compiler.compile(occurrence_query), batch_size=batch_size
            )
            occurrences = next(iter(occurrence_batches), [])
            if not occurrences:
                return
            doc_ids = tuple(dict.fromkeys(str(row["doc_id"]) for row in occurrences))
            normalized_query = Select(
                source=Table("normalized_documents"),
                projection=tuple(col(column) for column in normalized_columns),
                where=Membership(col("source_doc_id"), ValueList(doc_ids)),
            )
            normalized_rows: list[dict[str, Any]] = []
            for normalized_batch in self.executor.query_batches(
                self.executor.compiler.compile(normalized_query),
                batch_size=batch_size,
            ):
                normalized_rows.extend(normalized_batch)
            chosen = choose_normalized(normalized_rows)
            result = []
            for occurrence in occurrences:
                normalized = chosen.get(str(occurrence["doc_id"]))
                if normalized is not None:
                    result.append({**occurrence, **normalized})
                elif include_missing:
                    result.append(dict(occurrence))
            yield result
            last_doc_id = str(occurrences[-1]["doc_id"])
            last_occurrence_id = str(occurrences[-1]["occurrence_id"])

    def fetch_payloads(
        self, doc_ids: Sequence[str], *, chunk_size: int = 512
    ) -> Iterator[list[dict[str, Any]]]:
        """Fetch selected compressed payloads for a bounded doc_id set.

        Yields one list per chunk of ``doc_ids``. Each row carries the winning
        normalized artifact for its ``source_doc_id`` including the compressed
        ``normalized_payload`` blob and stored ``payload_sha256``. Only chunks
        containing at least one requested doc_id are queried.
        """
        if chunk_size < 1:
            raise ValueError("chunk_size must be positive")
        unique = list(dict.fromkeys(str(doc_id) for doc_id in doc_ids))
        for start in range(0, len(unique), chunk_size):
            chunk = tuple(unique[start : start + chunk_size])
            query = Select(
                source=Table("normalized_documents"),
                projection=tuple(col(column) for column in _normalized_columns(True)),
                where=Membership(col("source_doc_id"), ValueList(chunk)),
            )
            rows: list[dict[str, Any]] = []
            for batch in self.executor.query_batches(
                self.executor.compiler.compile(query), batch_size=chunk_size
            ):
                rows.extend(batch)
            chosen = choose_normalized(rows)
            yield [chosen[doc_id] for doc_id in chunk if doc_id in chosen]

    def close(self) -> None:
        if not self._closed:
            self.executor.close()
            self._closed = True

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


OCCURRENCE_COLUMNS = (
    "occurrence_id",
    "source_cik",
    "accession",
    "document_path",
    "form",
    "filing_date",
    "report_date",
    "doc_id",
)
NORMALIZED_METADATA_COLUMNS = (
    "normalized_artifact_id",
    "source_doc_id",
    "byte_size",
    "payload_sha256",
    "mime_type",
    "processor_fingerprint",
    "schema_version",
)
PAYLOAD_COLUMN = "normalized_payload"


def _normalized_columns(with_payload: bool) -> tuple[str, ...]:
    if with_payload:
        return NORMALIZED_METADATA_COLUMNS + (PAYLOAD_COLUMN,)
    return NORMALIZED_METADATA_COLUMNS


__all__ = ["PartitionBatchReader"]
