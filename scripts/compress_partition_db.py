"""Parallel utility to compress uncompressed payloads in SQLite partition and chunk databases in-place.

Compresses raw or normalized payloads using the canonical thread-local compress_payload()
across all worker chunk databases (.db) and finalized partition databases (.sqlite)
in parallel, followed by WAL checkpointing and VACUUM to reclaim disk pages.
"""

from __future__ import annotations

import argparse
import importlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from defs.runtime.paths import resolve_paths
from defs.runtime.resources import default_cpu_cores
from defs.sql import (
    Commit,
    Compare,
    ComparisonOp,
    QueryCompiler,
    Select,
    SqlDialect,
    Table,
    UnsafeStatement,
    Update,
    col,
    make_sql_executor,
    param,
)

schemas_025 = importlib.import_module("phases.025_webpage_storage.core.schemas")
DOCUMENT_BLOBS_TABLE = schemas_025.DOCUMENT_BLOBS_TABLE
NORMALIZED_DOCUMENTS_TABLE = schemas_025.NORMALIZED_DOCUMENTS_TABLE
compress_payload = schemas_025.compress_payload

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


def is_compressed(payload: bytes | None) -> bool:
    """Check if payload already has Zstandard magic header bytes."""
    if not payload:
        return False
    return payload.startswith(ZSTD_MAGIC)


def compress_single_database(
    db_path: Path,
    batch_size: int = 500,
) -> dict[str, float | int | str]:
    """Compress uncompressed blobs in a single SQLite database in-place (thread-safe)."""
    if not db_path.is_file():
        return {
            "db_name": db_path.name,
            "rows_compressed": 0,
            "initial_bytes": 0,
            "final_bytes": 0,
            "reclaimed_bytes": 0,
            "status": "missing",
        }

    initial_size = db_path.stat().st_size
    compiler = QueryCompiler(dialect=SqlDialect.SQLITE, allow_unsafe=True)
    executor = make_sql_executor(db_path, dialect=SqlDialect.SQLITE)

    target_tables = [
        (NORMALIZED_DOCUMENTS_TABLE, "normalized_artifact_id", "normalized_payload"),
        (DOCUMENT_BLOBS_TABLE, "doc_id", "raw_payload"),
    ]

    total_compressed = 0
    total_saved_bytes = 0
    summary_parts = []

    for table_name, pk_col, payload_col in target_tables:
        select_query = compiler.compile(
            Select(
                source=Table(table_name),
                projection=(col(pk_col), col(payload_col)),
            )
        )
        try:
            rows = executor.query(select_query)
        except Exception:  # noqa: BLE001, S112
            continue

        if not rows:
            continue

        uncompressed_in_table = 0
        table_before = 0
        table_after = 0

        for row in rows:
            row_pk = row[pk_col]
            payload = row[payload_col]
            if payload and not is_compressed(payload):
                table_before += len(payload)
                compressed = compress_payload(payload)
                table_after += len(compressed)
                uncompressed_in_table += 1

                update_stmt = compiler.compile(
                    Update(
                        table=table_name,
                        assignments=((payload_col, param(compressed)),),
                        where=Compare(col(pk_col), ComparisonOp.EQ, param(row_pk)),
                    )
                )
                executor.exec(update_stmt)

        if uncompressed_in_table > 0:
            executor.exec(compiler.compile(Commit()))
            total_compressed += uncompressed_in_table
            total_saved_bytes += table_before - table_after
            summary_parts.append(
                f"{table_name}: {uncompressed_in_table:,} rows "
                f"({table_before / (1024 * 1024):.1f}MB -> {table_after / (1024 * 1024):.1f}MB)"
            )

    executor.close()

    if total_compressed > 0:
        # Checkpoint WAL and reclaim free disk pages with VACUUM
        vacuum_executor = make_sql_executor(db_path, dialect=SqlDialect.SQLITE)
        vacuum_executor.exec(
            compiler.compile(UnsafeStatement("PRAGMA wal_checkpoint(TRUNCATE);"))
        )
        vacuum_executor.exec(compiler.compile(UnsafeStatement("VACUUM;")))
        vacuum_executor.exec(
            compiler.compile(UnsafeStatement("PRAGMA wal_checkpoint(TRUNCATE);"))
        )
        vacuum_executor.close()

    final_size = db_path.stat().st_size
    reclaimed = max(0, initial_size - final_size)

    return {
        "db_name": db_path.name,
        "db_path": str(db_path),
        "rows_compressed": total_compressed,
        "initial_bytes": initial_size,
        "final_bytes": final_size,
        "reclaimed_bytes": reclaimed,
        "summary": ", ".join(summary_parts) if summary_parts else "already compressed",
        "status": "ok",
    }


def find_target_databases(
    paths: list[Path] | None = None,
    run_id: str | None = None,
) -> list[Path]:
    """Find all chunk worker databases and partition databases."""
    found: list[Path] = []
    paths_resolver = resolve_paths()

    if paths:
        for p in paths:
            if p.is_file() and p.suffix in (".db", ".sqlite"):
                found.append(p)
            elif p.is_dir():
                found.extend(sorted(p.rglob("*.db")))
                found.extend(sorted(p.rglob("*.sqlite")))
        return sorted(set(found))

    # Search in transient run directory
    phase_paths = paths_resolver.phase("webpage_storage")
    if run_id:
        target_run = phase_paths.run(run_id).run_root
        if target_run.is_dir():
            found.extend(sorted(target_run.rglob("*.db")))
            found.extend(sorted(target_run.rglob("*.sqlite")))
    elif phase_paths.runs_root.is_dir():
        found.extend(sorted(phase_paths.runs_root.rglob("*.db")))
        found.extend(sorted(phase_paths.runs_root.rglob("*.sqlite")))

    # Search in finalized manifests directory
    manifests_dir = paths_resolver.dataset_manifests("filing_documents", "final")
    if manifests_dir.is_dir():
        found.extend(sorted(manifests_dir.rglob("*.sqlite")))
        found.extend(sorted(manifests_dir.rglob("*.db")))

    return sorted(set(found))


def compress_all_targets(
    targets: list[Path],
    workers: int = 4,
    batch_size: int = 500,
) -> dict[str, float | int]:
    """Process all target databases in parallel and report summary."""
    if not targets:
        print("No target databases (.db / .sqlite) found to compress.")
        return {
            "databases_processed": 0,
            "rows_compressed": 0,
            "initial_mb": 0.0,
            "final_mb": 0.0,
            "reclaimed_mb": 0.0,
        }

    effective_workers = max(1, min(workers, len(targets)))
    print(
        f"Found {len(targets)} database(s) to inspect & compress "
        f"(using {effective_workers} parallel workers):"
    )
    for t in targets[:8]:
        print(f"  - {t}")
    if len(targets) > 8:
        print(f"  ... and {len(targets) - 8} more.")

    t0 = time.time()
    grand_compressed = 0
    grand_initial = 0
    grand_final = 0
    grand_reclaimed = 0
    modified_count = 0
    completed_count = 0
    total_count = len(targets)
    print_lock = threading.Lock()

    def process_one(target_path: Path) -> dict[str, float | int | str]:
        return compress_single_database(target_path, batch_size=batch_size)

    with ThreadPoolExecutor(max_workers=effective_workers) as pool:
        futures = {pool.submit(process_one, t): t for t in targets}
        for future in as_completed(futures):
            res = future.result()
            with print_lock:
                completed_count += 1
                rows_comp = int(res["rows_compressed"])
                init_b = int(res["initial_bytes"])
                final_b = int(res["final_bytes"])
                rec_b = int(res["reclaimed_bytes"])

                grand_compressed += rows_comp
                grand_initial += init_b
                grand_final += final_b
                grand_reclaimed += rec_b

                if rows_comp > 0:
                    modified_count += 1
                    init_m = init_b / (1024 * 1024)
                    fin_m = final_b / (1024 * 1024)
                    rec_m = rec_b / (1024 * 1024)
                    pct = (rec_m / init_m) * 100 if init_m > 0 else 0.0
                    print(
                        f"[{completed_count:>3}/{total_count}] {res['db_name']}: "
                        f"{res['summary']} | {init_m:.1f}MB -> {fin_m:.1f}MB "
                        f"(reclaimed {rec_m:.1f}MB, -{pct:.1f}%)"
                    )
                else:
                    print(
                        f"[{completed_count:>3}/{total_count}] {res['db_name']}: {res['summary']}"
                    )

    elapsed = time.time() - t0
    init_mb = grand_initial / (1024 * 1024)
    final_mb = grand_final / (1024 * 1024)
    reclaimed_mb = grand_reclaimed / (1024 * 1024)
    pct = (reclaimed_mb / init_mb) * 100 if init_mb > 0 else 0.0

    print("\n" + "=" * 65)
    print("PARALLEL COMPRESSION SUMMARY")
    print(f"  Databases inspected: {total_count}")
    print(f"  Databases updated:   {modified_count}")
    print(f"  Total rows compressed: {grand_compressed:,}")
    print(f"  Total initial size:    {init_mb:,.2f} MB ({init_mb / 1024:,.2f} GB)")
    print(f"  Total final size:      {final_mb:,.2f} MB ({final_mb / 1024:,.2f} GB)")
    print(f"  Total disk reclaimed:  {reclaimed_mb:,.2f} MB ({pct:.1f}% reduction)")
    print(
        f"  Time elapsed:          {elapsed:.1f}s ({total_count / elapsed:.1f} dbs/s)"
    )
    print("=" * 65)

    return {
        "databases_processed": total_count,
        "databases_updated": modified_count,
        "rows_compressed": grand_compressed,
        "initial_mb": init_mb,
        "final_mb": final_mb,
        "reclaimed_mb": reclaimed_mb,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parallel utility to compress uncompressed payloads in partition and chunk databases in-place."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Optional explicit SQLite files or directories to compress.",
    )
    parser.add_argument(
        "--run-id",
        "-r",
        type=str,
        default=None,
        help="Specific run-id under transient storage to compress (e.g. c2f5).",
    )
    parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=default_cpu_cores(),
        help="Number of parallel worker threads (defaults to min(8, CPU cores)).",
    )
    parser.add_argument(
        "--batch-size",
        "-b",
        type=int,
        default=500,
        help="Batch size for progress updates.",
    )
    args = parser.parse_args()

    targets = find_target_databases(
        paths=args.paths if args.paths else None,
        run_id=args.run_id,
    )
    compress_all_targets(targets, workers=args.workers, batch_size=args.batch_size)


if __name__ == "__main__":
    main()
