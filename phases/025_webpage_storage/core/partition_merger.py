"""Merge immutable webpage-storage chunk databases into one partition database."""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path

from defs.sql import (
    Attach,
    Begin,
    Commit,
    Detach,
    DoNothing,
    Insert,
    Rollback,
    Select,
    SelectSource,
    Table,
    col,
    make_sql_executor,
)

from .schemas import (
    BLOB_COLUMNS,
    COMMITTED_CHUNK_COLUMNS,
    COMMITTED_CHUNKS_TABLE,
    DOCUMENT_BLOBS_TABLE,
    FILING_OCCURRENCES_TABLE,
    OCCURRENCE_COLUMNS,
    CommittedChunk,
    create_partition_schema,
)


@dataclass(frozen=True, slots=True)
class PartitionMergeResult:
    """Summary of one partition merge operation."""

    partition_db_path: str
    committed_chunk_ids: tuple[str, ...]
    skipped_chunk_ids: tuple[str, ...]
    blob_rows: int
    occurrence_rows: int
    audit_rows: int

    @property
    def committed_chunks(self) -> tuple[str, ...]:
        return self.committed_chunk_ids

    def to_dict(self) -> dict:
        return asdict(self)


def _select_columns(table: str, columns: tuple[str, ...], qualifier: str | None = None):
    return Select(
        source=Table(table, alias=qualifier),
        projection=tuple(col(column, qualifier) for column in columns),
    )


def _insert_from(
    target: str,
    columns: tuple[str, ...],
    source: str,
    alias: str,
    *,
    on_conflict: DoNothing | None = None,
) -> Insert:
    return Insert(
        table=target,
        columns=columns,
        source=SelectSource(_select_columns(source, columns, alias)),
        on_conflict=on_conflict,
    )


def merge_partition(
    partition_db_path: str | Path, chunk_dbs: Iterable[str | Path]
) -> PartitionMergeResult:
    """Merge chunk databases into ``partition_db_path`` atomically.

    Chunk identity comes from the chunk's ``_committed_chunks`` audit row.  A
    chunk already present in the partition is not copied or audited again.
    Attachments are deliberately established before ``BEGIN`` because SQLite
    cannot reliably attach or detach databases while a write transaction is
    active.
    """

    partition_path = Path(partition_db_path)
    partition_path.touch(exist_ok=True)
    executor = make_sql_executor(partition_path, dialect="sqlite")
    attached: list[str] = []
    eligible: list[tuple[str, list[dict]]] = []
    skipped: list[str] = []
    committed: list[str] = []
    try:
        create_partition_schema(executor)
        existing_rows = executor.query(
            executor.compiler.compile(
                _select_columns(COMMITTED_CHUNKS_TABLE, ("chunk_id",))
            )
        )
        existing_ids = {str(row["chunk_id"]) for row in existing_rows}

        for index, chunk_path in enumerate(chunk_dbs):
            alias = f"chunk_{index:05d}"
            executor.exec(
                executor.compiler.compile(
                    Attach(path=str(chunk_path), alias=alias, read_only=True)
                )
            )
            attached.append(alias)
            audit_rows = executor.query(
                executor.compiler.compile(
                    _select_columns(
                        f"{alias}.{COMMITTED_CHUNKS_TABLE}",
                        COMMITTED_CHUNK_COLUMNS,
                        alias,
                    )
                )
            )
            if not audit_rows:
                raise ValueError(f"chunk database has no {COMMITTED_CHUNKS_TABLE} row")
            for row in audit_rows:
                CommittedChunk.from_row(row)
            chunk_ids = {str(row["chunk_id"]) for row in audit_rows}
            if chunk_ids <= existing_ids:
                skipped.extend(sorted(chunk_ids))
            else:
                eligible.append((alias, audit_rows))

        executor.exec(executor.compiler.compile(Begin()))
        blob_rows = occurrence_rows = audit_count = 0
        try:
            for alias, audit_rows in eligible:
                new_audits = [
                    row
                    for row in audit_rows
                    if str(row["chunk_id"]) not in existing_ids
                ]
                if not new_audits:
                    continue
                executor.exec(
                    executor.compiler.compile(
                        _insert_from(
                            DOCUMENT_BLOBS_TABLE,
                            BLOB_COLUMNS,
                            f"{alias}.{DOCUMENT_BLOBS_TABLE}",
                            alias,
                            on_conflict=DoNothing(),
                        )
                    )
                )
                executor.exec(
                    executor.compiler.compile(
                        _insert_from(
                            FILING_OCCURRENCES_TABLE,
                            OCCURRENCE_COLUMNS,
                            f"{alias}.{FILING_OCCURRENCES_TABLE}",
                            alias,
                            on_conflict=DoNothing(),
                        )
                    )
                )
                executor.exec(
                    executor.compiler.compile(
                        _insert_from(
                            COMMITTED_CHUNKS_TABLE,
                            COMMITTED_CHUNK_COLUMNS,
                            f"{alias}.{COMMITTED_CHUNKS_TABLE}",
                            alias,
                            on_conflict=DoNothing(),
                        )
                    )
                )
                committed_ids = tuple(str(row["chunk_id"]) for row in new_audits)
                blob_rows += len(
                    executor.query(
                        executor.compiler.compile(
                            _select_columns(
                                f"{alias}.{DOCUMENT_BLOBS_TABLE}", BLOB_COLUMNS, alias
                            )
                        )
                    )
                )
                occurrence_rows += len(
                    executor.query(
                        executor.compiler.compile(
                            _select_columns(
                                f"{alias}.{FILING_OCCURRENCES_TABLE}",
                                OCCURRENCE_COLUMNS,
                                alias,
                            )
                        )
                    )
                )
                audit_count += len(committed_ids)
                committed.extend(committed_ids)
                existing_ids.update(committed_ids)
            executor.exec(executor.compiler.compile(Commit()))
        except Exception:
            # Rollback is intentionally compiled by the same SQL boundary.
            executor.exec(executor.compiler.compile(Rollback()))
            raise
    finally:
        for alias in reversed(attached):
            with suppress(Exception):
                executor.exec(executor.compiler.compile(Detach(alias=alias)))
        executor.close()

    return PartitionMergeResult(
        partition_db_path=str(partition_path),
        committed_chunk_ids=tuple(sorted(committed)),
        skipped_chunk_ids=tuple(sorted(set(skipped))),
        blob_rows=blob_rows,
        occurrence_rows=occurrence_rows,
        audit_rows=audit_count,
    )


__all__ = ["PartitionMergeResult", "merge_partition"]
