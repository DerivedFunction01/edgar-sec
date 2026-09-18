#!/usr/bin/env python3
"""One-off migration script from singular submission_metadata.parquet to S0 snapshot."""

from __future__ import annotations

import argparse
import concurrent.futures
import importlib
import json
import logging
import math
import os
import shutil
import sys
from pathlib import Path

# Add repo root to sys.path for direct execution
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tqdm import tqdm

from defs.runtime.artifacts import (
    file_sha256,
    make_snapshot_manifest,
    publish_snapshot_manifest,
    resolve_manifest,
)
from defs.runtime.paths import resolve_paths
from defs.runtime.resources import derive_resources
from defs.storage import (
    FinalizedDataset,
    StorageError,
    connect,
    load_json,
    parquet_column_bounds,
    parquet_column_names,
)

_paths_mod = importlib.import_module("phases.01_metadata_extraction.core.paths")
resolve_metadata_paths = _paths_mod.resolve_metadata_paths

_schemas_mod = importlib.import_module("phases.01_metadata_extraction.core.schemas")
SCHEMA_VERSION = _schemas_mod.SCHEMA_VERSION
SUBMISSION_METADATA_SCHEMA = _schemas_mod.SUBMISSION_METADATA_SCHEMA

logger = logging.getLogger("migrate_snapshot")


def _quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _format_summary_table(
    *,
    source_path: Path,
    snapshot_id: str,
    total_source_rows: int,
    shard_count: int,
    rows_per_shard: int,
    resolved_parts: list[dict],
    dry_run: bool,
) -> str:
    lines = [
        "=" * 80,
        f"Snapshot Migration Summary (snapshot_id={snapshot_id}, dry_run={dry_run})",
        "=" * 80,
        f"Source:           {source_path}",
        f"Total CIK Rows:   {total_source_rows:,}",
        f"Total Shards:     {shard_count} (target ~{rows_per_shard:,} CIKs/shard)",
        "-" * 80,
        f"{'Shard ID':<12} {'CIK Range':<26} {'Rows':>8} {'Size (MB)':>12} {'SHA-256':>14}",
        "-" * 80,
    ]
    total_bytes = 0
    total_rows = 0
    for part in resolved_parts:
        shard_id = part["shard_id"]
        cik_min = str(part.get("cik_min", ""))
        cik_max = str(part.get("cik_max", ""))
        cik_range = f"{cik_min}..{cik_max}" if cik_min and cik_max else "-"
        rows = part["row_count"]
        size_mb = part["byte_count"] / (1024 * 1024)
        sha_prefix = part["artifact_sha256"][:12] + "..."
        total_bytes += part["byte_count"]
        total_rows += rows
        lines.append(
            f"{shard_id:<12} {cik_range:<26} {rows:>8,d} {size_mb:>11.2f} MB {sha_prefix:>14}"
        )
    lines.extend(
        [
            "-" * 80,
            f"{'Total':<12} {f'100% ({len(resolved_parts)} parts)':<26} {total_rows:>8,d} {total_bytes / (1024 * 1024):>11.2f} MB",
            "=" * 80,
        ]
    )
    return "\n".join(lines)


def _export_one_shard(
    *,
    source_path: str,
    staging_dir: Path,
    root: Path,
    snapshot_id: str,
    shard_idx: int,
    min_cik: str,
    max_cik: str,
    expected_rows: int,
    target_part_mb: int,
    temp_dir: str | None = None,
) -> dict:
    shard_name = f"shard-{shard_idx:04d}"
    shard_stage = staging_dir / shard_name
    shard_stage.mkdir(parents=True, exist_ok=True)
    part_stage = shard_stage / "part-000.parquet"

    # Dedicated DuckDB connection per worker thread
    with connect(threads=1, temp_directory=temp_dir) as con:
        query = (
            f"SELECT * FROM read_parquet({_quote(str(source_path))}) "
            f"WHERE cik >= {_quote(min_cik)} AND cik <= {_quote(max_cik)} "
            f"ORDER BY cik"
        )
        con.execute(
            f"COPY ({query}) TO {_quote(str(part_stage))} (FORMAT PARQUET, COMPRESSION 'zstd')"
        )
        shard_row_count = con.execute(
            f"SELECT count(*) FROM read_parquet({_quote(str(part_stage))})"
        ).fetchone()[0]

        if shard_row_count != expected_rows:
            raise StorageError(
                f"shard {shard_name} row count mismatch: expected {expected_rows}, got {shard_row_count}"
            )

        cik_min, cik_max = parquet_column_bounds(con, part_stage, "cik")

    part_hash = file_sha256(str(part_stage))
    part_size = part_stage.stat().st_size
    if target_part_mb and (part_size > target_part_mb * 1024 * 1024):
        logger.warning(
            "part %s exceeds target size (%d MB > %d MB)",
            shard_name,
            part_size // (1024 * 1024),
            target_part_mb,
        )

    metadata_paths = resolve_metadata_paths(env={"ARTIFACTS_ROOT": str(root)})
    final_part_path = (
        metadata_paths.snapshot_parts_dir(snapshot_id, shard_name) / "part-000.parquet"
    )
    return {
        "path": str(final_part_path.relative_to(root)),
        "artifact_sha256": part_hash,
        "row_count": shard_row_count,
        "byte_count": part_size,
        "cik_min": cik_min,
        "cik_max": cik_max,
        "shard_id": shard_name,
        "shard_idx": shard_idx,
    }


def migrate_singular_to_snapshot(
    source_path: str | Path,
    *,
    artifacts_root: str | Path,
    snapshot_id: str = "S0",
    shard_count: int | None = None,
    rows_per_shard: int = 2500,
    target_part_mb: int = 128,
    workers: int | None = None,
    set_current: bool = True,
    dry_run: bool = False,
) -> dict:
    """Migrate a singular submission_metadata.parquet to a multi-part S0 snapshot in parallel."""
    root = Path(artifacts_root).resolve()
    metadata_paths = resolve_metadata_paths(env={"ARTIFACTS_ROOT": str(root)})
    source = Path(source_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"source artifact does not exist: {source}")

    source_hash = file_sha256(str(source))
    source_cols = parquet_column_names(str(source))
    if source_cols != SUBMISSION_METADATA_SCHEMA.names:
        raise StorageError(
            f"source schema mismatch: expected {SUBMISSION_METADATA_SCHEMA.names}, got {source_cols}"
        )

    dest_snapshot_dir = metadata_paths.snapshot_dir(snapshot_id)
    if dest_snapshot_dir.exists() and not dry_run:
        manifest_p = metadata_paths.snapshot_manifest_path(snapshot_id)
        if manifest_p.is_file():
            manifest = load_json(manifest_p)
            if (
                manifest.get("provenance", {}).get("source_artifact_sha256")
                == source_hash
            ):
                logger.info(
                    "snapshot %s already exists and matches source hash", snapshot_id
                )
                return {
                    "status": "already_migrated",
                    "snapshot_id": snapshot_id,
                    "manifest_path": str(manifest_p),
                    "source_artifact_sha256": source_hash,
                }

    resources = derive_resources()
    max_workers = workers or max(1, resources.threads)

    staging_dir = root / "transient" / "metadata" / "migration" / snapshot_id
    if staging_dir.exists():
        shutil.rmtree(staging_dir, ignore_errors=True)
    staging_dir.mkdir(parents=True, exist_ok=True)

    with connect(
        threads=resources.threads,
        memory_limit=resources.memory_limit,
        temp_directory=resources.temp_directory,
    ) as con:
        # Step 1: Read all sorted CIKs in one quick pass (no struct reading)
        logger.info("indexing CIKs from %s...", source.name)
        all_ciks = [
            r[0]
            for r in con.execute(
                f"SELECT cik FROM read_parquet({_quote(str(source))}) ORDER BY cik"
            ).fetchall()
        ]
        total_source_rows = len(all_ciks)

    # Step 2: Determine shard count based on record size (e.g. 40k -> 16, 80k -> 32, 120k -> 48)
    if shard_count is None or shard_count <= 0:
        effective_shard_count = max(1, math.ceil(total_source_rows / rows_per_shard))
    else:
        effective_shard_count = shard_count

    logger.info(
        "partitioning %d rows into %d contiguous range shards (~%d CIKs/shard, %d parallel workers)...",
        total_source_rows,
        effective_shard_count,
        math.ceil(total_source_rows / effective_shard_count),
        max_workers,
    )

    # Step 3: Compute contiguous range slices for each shard
    slices = []
    for shard_idx in range(effective_shard_count):
        start_idx = shard_idx * total_source_rows // effective_shard_count
        end_idx = (shard_idx + 1) * total_source_rows // effective_shard_count
        shard_ciks = all_ciks[start_idx:end_idx]
        if not shard_ciks:
            continue
        slices.append((shard_idx, shard_ciks[0], shard_ciks[-1], len(shard_ciks)))

    # Step 4: Export shards in parallel with ThreadPoolExecutor & tqdm
    resolved_parts: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(max_workers, len(slices))
    ) as executor:
        futures = {
            executor.submit(
                _export_one_shard,
                source_path=str(source),
                staging_dir=staging_dir,
                root=root,
                snapshot_id=snapshot_id,
                shard_idx=shard_idx,
                min_cik=min_cik,
                max_cik=max_cik,
                expected_rows=expected_rows,
                target_part_mb=target_part_mb,
                temp_dir=resources.temp_directory,
            ): (shard_idx, min_cik, max_cik)
            for shard_idx, min_cik, max_cik, expected_rows in slices
        }
        with tqdm(
            total=len(futures), desc="Exporting shards in parallel", unit="shard"
        ) as progress:
            for future in concurrent.futures.as_completed(futures):
                part_info = future.result()
                resolved_parts.append(part_info)
                progress.set_postfix(
                    {
                        "shard": part_info["shard_id"],
                        "ciks": f"{part_info['cik_min']}..{part_info['cik_max']}",
                        "rows": part_info["row_count"],
                        "mb": f"{part_info['byte_count'] / (1024 * 1024):.1f}",
                    }
                )
                progress.update(1)

    resolved_parts.sort(key=lambda p: p["shard_idx"])
    total_migrated_rows = sum(p["row_count"] for p in resolved_parts)

    if total_migrated_rows != total_source_rows:
        raise StorageError(
            f"row count mismatch during migration: source had {total_source_rows}, parts have {total_migrated_rows}"
        )

    summary_text = _format_summary_table(
        source_path=source,
        snapshot_id=snapshot_id,
        total_source_rows=total_source_rows,
        shard_count=len(resolved_parts),
        rows_per_shard=rows_per_shard,
        resolved_parts=resolved_parts,
        dry_run=dry_run,
    )
    print("\n" + summary_text + "\n")

    if dry_run:
        shutil.rmtree(staging_dir, ignore_errors=True)
        return {
            "status": "dry_run_success",
            "snapshot_id": snapshot_id,
            "source_row_count": total_source_rows,
            "part_count": len(resolved_parts),
            "parts": resolved_parts,
        }

    # Move staged parts to finalized snapshot parts directory
    for part_info in resolved_parts:
        staged = staging_dir / part_info["shard_id"] / "part-000.parquet"
        target = root / part_info["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if file_sha256(str(target)) != part_info["artifact_sha256"]:
                raise StorageError(f"conflicting part in destination: {target}")
        else:
            os.replace(staged, target)

    shutil.rmtree(staging_dir, ignore_errors=True)

    # Clean up part metadata for manifest (remove internal shard_idx)
    published_parts = [
        {k: v for k, v in p.items() if k != "shard_idx"} for p in resolved_parts
    ]

    manifest_data = make_snapshot_manifest(
        snapshot_id=snapshot_id,
        schema_version=SCHEMA_VERSION,
        resolved_parts=published_parts,
        effective_cik_count=total_migrated_rows,
        provenance={
            "migration_source": str(
                source.relative_to(root)
                if str(source).startswith(str(root))
                else source
            ),
            "source_artifact_sha256": source_hash,
            "shard_count": len(resolved_parts),
        },
    )
    manifest_path = publish_snapshot_manifest(
        manifest_data,
        artifacts_root=root,
        set_current=set_current,
    )

    # Validate readback
    with FinalizedDataset(manifest_path, artifacts_root=root) as dataset:
        if dataset.count() != total_source_rows:
            raise StorageError("read-back validation failed on migrated snapshot")
        if dataset.columns != source_cols:
            raise StorageError("read-back columns failed on migrated snapshot")

    logger.info(
        "migration complete: snapshot %s published with %d parts (%d rows) -> %s",
        snapshot_id,
        len(resolved_parts),
        total_migrated_rows,
        manifest_path,
    )
    return {
        "status": "migrated",
        "snapshot_id": snapshot_id,
        "manifest_path": str(manifest_path),
        "source_row_count": total_source_rows,
        "migrated_row_count": total_migrated_rows,
        "part_count": len(resolved_parts),
        "source_artifact_sha256": source_hash,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Migrate singular submission_metadata.parquet to an immutable S0 snapshot"
    )
    parser.add_argument(
        "--source-manifest",
        help="Path or artifact ID of existing singular metadata manifest",
    )
    parser.add_argument(
        "--source-file",
        help="Direct path to existing submission_metadata.parquet file",
    )
    parser.add_argument(
        "--artifacts-root",
        default=".artifacts",
        help="Path to artifacts root (default: .artifacts)",
    )
    parser.add_argument(
        "--snapshot-id",
        default="S0",
        help="Snapshot ID for the migrated snapshot (default: S0)",
    )
    parser.add_argument(
        "--shard-count",
        type=int,
        default=None,
        help="Explicit number of shards (default: auto-calculated from row count, ~2500 CIKs/shard)",
    )
    parser.add_argument(
        "--rows-per-shard",
        type=int,
        default=2500,
        help="Target CIK rows per shard when auto-calculating shard count (default: 2500)",
    )
    parser.add_argument(
        "--target-part-mb",
        type=int,
        default=128,
        help="Target size per part in MB (default: 128)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of concurrent worker threads (default: hardware thread profile)",
    )
    parser.add_argument(
        "--no-set-current",
        action="store_true",
        help="Do not advance current snapshot pointer to S0",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate migration without publishing snapshot",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    root = Path(args.artifacts_root).resolve()
    if args.source_manifest:
        _manifest, source_file = resolve_manifest(
            args.source_manifest, artifacts_root=str(root)
        )
    elif args.source_file:
        source_file = Path(args.source_file).resolve()
    else:
        # Default to canonical published dataset
        paths = resolve_paths(env={"ARTIFACTS_ROOT": str(root)})
        source_file = paths.published_dataset_path(
            "metadata", "submission_metadata", "parquet"
        )

    result = migrate_singular_to_snapshot(
        source_file,
        artifacts_root=root,
        snapshot_id=args.snapshot_id,
        shard_count=args.shard_count,
        rows_per_shard=args.rows_per_shard,
        target_part_mb=args.target_part_mb,
        workers=args.workers,
        set_current=not args.no_set_current,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
