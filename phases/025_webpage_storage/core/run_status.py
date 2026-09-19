"""Run and finalized-partition status reporting."""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path

from defs.runtime.paths import resolve_paths
from defs.sql import (
    Aggregate,
    AggregateFunction,
    Select,
    SqlDialect,
    Star,
    Table,
    make_sql_executor,
)

from .partition_handoff import finalized_partition_dir, validate_handoff
from .schemas import (
    ACQUISITION_FAILURES_TABLE,
    COMMITTED_CHUNKS_TABLE,
    DOCUMENT_BLOBS_TABLE,
    FILING_OCCURRENCES_TABLE,
)


def _count_table(executor, table: str) -> int:
    query = Select(
        source=Table(table),
        projection=(Aggregate(AggregateFunction.COUNT, Star()),),
    )
    row = executor.query_one(executor.compiler.compile(query))
    if row:
        val = next(iter(row.values()))
        return int(val) if val is not None else 0
    return 0


def status(database: str | None = None, run_id: str | None = None) -> dict:
    """Report one database or run-level finalized partition coverage."""
    if database:
        path = Path(database)
        if not path.is_file():
            return {
                "database": database,
                "exists": False,
                "blobs": 0,
                "occurrences": 0,
                "failures": 0,
                "committed_chunks": 0,
            }
        executor = make_sql_executor(database, dialect=SqlDialect.SQLITE)
        try:
            return {
                "database": database,
                "exists": True,
                "blobs": _count_table(executor, DOCUMENT_BLOBS_TABLE),
                "occurrences": _count_table(executor, FILING_OCCURRENCES_TABLE),
                "failures": _count_table(executor, ACQUISITION_FAILURES_TABLE),
                "committed_chunks": _count_table(executor, COMMITTED_CHUNKS_TABLE),
            }
        finally:
            executor.close()

    target_run_id = run_id or "run-default"
    run_paths = resolve_paths("webpage_storage", target_run_id)
    meta_file = run_paths.run_root / "run_metadata.json"
    meta = {}
    if meta_file.is_file():
        with suppress(Exception):
            from defs.storage import load_json

            meta = load_json(meta_file)

    chunk_dbs = [
        p for p in sorted(run_paths.workers_root.rglob("chunk-*.db")) if p.is_file()
    ]
    finalized_dir = finalized_partition_dir(target_run_id)
    finalized = (
        sorted(finalized_dir.glob("partition-*.sqlite"))
        if finalized_dir.is_dir()
        else []
    )
    handoffs = []
    invalid_handoffs = []
    for path in finalized:
        try:
            handoffs.append(validate_handoff(path))
        except (OSError, ValueError) as exc:
            invalid_handoffs.append({"path": str(path), "error": str(exc)})
    expected_count = int(meta.get("partition_count") or 0)
    partition_ids = sorted(
        int(item["partition_id"]) for item in handoffs if "partition_id" in item
    )
    expected_ids = list(range(1, expected_count + 1)) if expected_count else []
    return {
        "run_id": target_run_id,
        "exists": run_paths.run_root.exists(),
        "metadata": meta,
        "chunk_dbs_count": len(chunk_dbs),
        "finalized_partition_dir": str(finalized_dir),
        "finalized_partitions": [str(path) for path in finalized],
        "finalized_partition_ids": partition_ids,
        "missing_partition_ids": [
            pid for pid in expected_ids if pid not in partition_ids
        ],
        "invalid_handoffs": invalid_handoffs,
        "snapshot_eligible": bool(
            expected_ids and partition_ids == expected_ids and not invalid_handoffs
        ),
    }


__all__ = ["status"]
