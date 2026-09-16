#!/usr/bin/env python3
"""Prune duplicate raw blobs from Phase 2.5 Webpage Storage SQLite databases.

Zeros out `document_blobs.raw_payload` (setting it to NULL) while preserving
all metadata (doc_id, accession, byte_size, raw_payload_sha256) and all
normalized_documents. Reclaims physical disk space using SQLite VACUUM.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from concurrent.futures import ThreadPoolExecutor, as_completed

from tqdm import tqdm

from defs.runtime.paths import resolve_paths
from defs.runtime.resources import default_cpu_cores
from defs.sql import (
    Aggregate,
    AggregateFunction,
    BooleanGroup,
    Compare,
    ComparisonOp,
    Literal,
    Pragma,
    QueryCompiler,
    Select,
    SqlDialect,
    Star,
    Table,
    UnsafeStatement,
    col,
    make_sql_executor,
)


def _format_size(num_bytes: int) -> str:
    """Format bytes into human-readable units."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:3.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} PB"


def _get_db_disk_size(db_path: Path) -> int:
    """Sum total size of db, -wal, and -shm files."""
    total = 0
    for ext in ("", "-wal", "-shm"):
        sidecar = Path(str(db_path) + ext)
        if sidecar.is_file():
            try:
                total += sidecar.stat().st_size
            except OSError:
                pass
    return total


def prune_sqlite_database(db_path: Path, dry_run: bool = False) -> dict[str, int | str]:
    """Prune raw_payload column from document_blobs table in one SQLite database."""
    result: dict[str, int | str] = {
        "path": str(db_path),
        "db_name": db_path.name,
        "initial_bytes": _get_db_disk_size(db_path),
        "final_bytes": _get_db_disk_size(db_path),
        "reclaimed_bytes": 0,
        "pruned_blobs": 0,
        "status": "skipped",
    }

    if not db_path.is_file():
        return result

    try:
        compiler = QueryCompiler(dialect=SqlDialect.SQLITE, allow_unsafe=True)
        executor = make_sql_executor(db_path, dialect=SqlDialect.SQLITE)
        try:
            # Set busy timeout
            executor.exec(compiler.compile(Pragma("busy_timeout", 10000)))

            # Check if document_blobs exists
            check_table = Select(
                source=Table("sqlite_master"),
                projection=(Aggregate(AggregateFunction.COUNT, Star()),),
                where=BooleanGroup.and_(
                    Compare(col("type"), ComparisonOp.EQ, Literal("table")),
                    Compare(col("name"), ComparisonOp.EQ, Literal("document_blobs")),
                ),
            )
            table_row = executor.query_one(compiler.compile(check_table))
            table_exists = table_row and next(iter(table_row.values()), 0) > 0
            if not table_exists:
                result["status"] = "no_document_blobs_table"
                return result

            # Check if raw_payload column exists in table
            pragma_info = executor.query(
                compiler.compile(UnsafeStatement("PRAGMA table_info(document_blobs);"))
            )
            column_names = {row["name"] for row in pragma_info if "name" in row}
            has_raw = "raw_payload" in column_names

            # Check for unvacuumed freelist pages
            freelist_row = executor.query_one(
                compiler.compile(UnsafeStatement("PRAGMA freelist_count;"))
            )
            freelist_count = (
                int(next(iter(freelist_row.values()), 0)) if freelist_row else 0
            )

            if not has_raw and freelist_count == 0:
                result["status"] = "already_pruned"
                return result

            count_query = Select(
                source=Table("document_blobs"),
                projection=(Aggregate(AggregateFunction.COUNT, Star()),),
            )
            count_row = executor.query_one(compiler.compile(count_query))
            row_count = int(next(iter(count_row.values()), 0)) if count_row else 0
            result["pruned_blobs"] = row_count if has_raw else 0

            if dry_run:
                result["status"] = "dry_run"
                return result

            if has_raw:
                # Drop raw_payload column directly
                executor.exec(
                    compiler.compile(
                        UnsafeStatement(
                            "ALTER TABLE document_blobs DROP COLUMN raw_payload;"
                        )
                    )
                )

            # Checkpoint WAL, Vacuum to reclaim physical file pages, and Checkpoint again
            executor.exec(
                compiler.compile(UnsafeStatement("PRAGMA wal_checkpoint(TRUNCATE);"))
            )
            executor.exec(compiler.compile(UnsafeStatement("VACUUM;")))
            executor.exec(
                compiler.compile(UnsafeStatement("PRAGMA wal_checkpoint(TRUNCATE);"))
            )
        finally:
            executor.close()

        final_size = _get_db_disk_size(db_path)
        result["final_bytes"] = final_size
        result["reclaimed_bytes"] = max(0, int(result["initial_bytes"]) - final_size)
        result["status"] = "pruned"
    except Exception as exc:  # noqa: BLE001
        result["status"] = f"error: {exc}"

    return result


def find_target_databases(
    paths: list[Path] | None = None,
    artifacts_root: Path | None = None,
    run_id: str | None = None,
) -> list[Path]:
    """Discover all chunk and partition databases."""
    found: list[Path] = []
    if paths:
        for p in paths:
            if p.is_file() and p.suffix in (".db", ".sqlite"):
                found.append(p)
            elif p.is_dir():
                found.extend(sorted(p.rglob("*.db")))
                found.extend(sorted(p.rglob("*.sqlite")))
        return sorted(set(found))

    env = {"ARTIFACTS_ROOT": str(artifacts_root)} if artifacts_root else None
    paths_resolver = (
        resolve_paths("webpage_storage", run_id, env=env)
        if run_id
        else resolve_paths("webpage_storage", env=env)
    )

    if run_id:
        target_run = paths_resolver.run_root
        if target_run.is_dir():
            found.extend(sorted(target_run.rglob("*.db")))
            found.extend(sorted(target_run.rglob("*.sqlite")))
    else:
        runs_dir = paths_resolver.runs_root
        if runs_dir.is_dir():
            found.extend(sorted(runs_dir.rglob("*.db")))
            found.extend(sorted(runs_dir.rglob("*.sqlite")))

    manifests_dir = resolve_paths(env=env).dataset_manifests(
        "filing_documents", "final"
    )
    if manifests_dir.is_dir():
        found.extend(sorted(manifests_dir.rglob("*.sqlite")))
        found.extend(sorted(manifests_dir.rglob("*.db")))

    return sorted(set(found))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prune duplicate raw blobs from Webpage Storage databases."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Optional explicit SQLite files or directories to prune.",
    )
    parser.add_argument(
        "--artifacts-root",
        default=None,
        help="Path to artifacts root (defaults to configured .artifacts)",
    )
    parser.add_argument(
        "--run-id",
        "-r",
        default=None,
        help="Specific run ID to prune (e.g. c2f5 or local)",
    )
    parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=None,
        help="Number of concurrent worker threads (defaults to system CPU budget)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect databases without modifying them",
    )
    args = parser.parse_args()

    artifacts_root = (
        Path(args.artifacts_root).resolve()
        if args.artifacts_root
        else Path(resolve_paths().artifacts_root).resolve()
    )

    target_dbs = find_target_databases(
        paths=args.paths if args.paths else None,
        artifacts_root=artifacts_root,
        run_id=args.run_id,
    )

    if not target_dbs:
        print("No chunk or partition databases found.")
        return 0

    workers = (
        args.workers
        if args.workers is not None and args.workers > 0
        else default_cpu_cores()
    )

    mode_tag = "[DRY RUN] " if args.dry_run else ""
    print(
        f"{mode_tag}Found {len(target_dbs)} database(s) to process with {workers} worker thread(s)."
    )
    print("-" * 80)
    print(f" {'Database':<46} {'Blobs':<8} {'Before':<10} {'After':<10} {'Status'}")
    print("-" * 80)

    total_initial = 0
    total_final = 0
    total_blobs_pruned = 0
    results: list[dict[str, int | str]] = []

    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(prune_sqlite_database, db, dry_run=args.dry_run): db
            for db in target_dbs
        }
        with tqdm(
            total=len(target_dbs), desc="Pruning databases", unit="db", leave=False
        ) as pbar:
            for fut in as_completed(futures):
                res = fut.result()
                results.append(res)
                total_initial += int(res["initial_bytes"])
                total_final += int(res["final_bytes"])
                total_blobs_pruned += int(res["pruned_blobs"])
                pbar.update(1)

    # Sort results deterministically by database path for clean presentation
    for res in sorted(results, key=lambda r: str(r["path"])):
        db_path = Path(str(res["path"]))
        db_name = (
            f".../{db_path.parent.parent.name}/{db_path.parent.name}/{db_path.name}"
            if len(str(db_path)) > 45
            else str(db_path)
        )
        print(
            f" {db_name:<46} {res['pruned_blobs']:<8} "
            f"{_format_size(int(res['initial_bytes'])):<10} "
            f"{_format_size(int(res['final_bytes'])):<10} "
            f"{res['status']}"
        )

    elapsed = time.monotonic() - start
    reclaimed = max(0, total_initial - total_final)
    print("-" * 80)
    print(
        f"Summary: Processed {len(target_dbs)} databases ({total_blobs_pruned} blobs pruned) in {elapsed:.1f}s."
    )
    print(
        f"Total Space: {_format_size(total_initial)} -> {_format_size(total_final)} "
        f"(Reclaimed: {_format_size(reclaimed)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
