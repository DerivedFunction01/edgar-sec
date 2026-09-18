"""Orchestration functions exposed by the barrel: build_plan, preview_sample,
run_chunk, get_status, merge. Entry points must import from here and
must not duplicate fetching, normalization, or checkpoint logic."""

from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from defs.runtime.paths import resolve_paths
from defs.storage import load_json

from .augmentation import (
    load_plan_rows,
    output_paths,
    publish_snapshot,
)
from .chunks import (
    chunk_ciks,
    plan_hash,
    select_chunk,
)
from .config import RunOptions, validate_plan_against_options
from .fetch import build_client as _build_client
from .fetch import fetch_and_normalize as _fetch_and_normalize
from .merge import (
    MergeError,
    MergeReport,
    merge_partition,
    merge_partition_artifacts,
)
from .normalize import normalize_submissions
from .planning import build_plan
from .schemas import SCHEMA_VERSION, TERMINAL_STATUSES
from .storage import make_checkpoint_store, make_phase_store

logger = logging.getLogger("metadata")


def utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_plan(options: RunOptions | None = None) -> dict:
    path = os.path.join(options.artifacts_dir if options else "", "plan.json")
    if not options:
        # Fallback for callers that only have a path; skip freshness validation.
        if not os.path.exists(path):
            raise FileNotFoundError(f"plan.json not found at {path}; run `plan` first")
        plan = load_json(path)
        expected = plan.get("plan_hash")
        if expected and plan_hash(plan) != expected:
            raise ValueError(
                "plan.json hash mismatch: the manifest was modified after creation"
            )
        return plan
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"plan.json not found in {options.artifacts_dir}; run `plan` first"
        )
    plan = load_json(path)
    expected = plan.get("plan_hash")
    if expected and plan_hash(plan) != expected:
        raise ValueError(
            "plan.json hash mismatch: the manifest was modified after creation"
        )
    validate_plan_against_options(plan, options)
    return plan


def preview_sample(options: RunOptions, sample_size: int = 3) -> dict:
    from .preview import preview_sample as run_preview

    return run_preview(options, sample_size)


def run_chunk(options: RunOptions, progress=None) -> dict:
    """`run`: process exactly one chunk-id from the matching plan.json.

    Fetches each assigned CIK, follows every historical submissions file,
    combines all filing records into the CIK's nested filings list, and
    writes a validated atomic checkpoint. Resumes from a valid completed
    checkpoint, never from an in-memory counter. ``progress`` receives one
    event dict per completed CIK (type ``cik_done``) or worker failure
    (type ``worker_failed``), each carrying the client's HTTP metrics."""
    plan = load_plan(options)
    if options.chunk_id is None:
        raise ValueError("--chunk-id is required for run")
    if options.storage_format != plan.get("storage_format", "parquet"):
        raise ValueError("storage format does not match plan.json")

    rows, report = load_plan_rows(options, plan)
    if report["fingerprint"] != plan.get("input_fingerprint"):
        raise ValueError(
            "input fingerprint mismatch between CSV and plan.json; regenerate the plan"
        )
    if options.partition_id is None:
        chunk = select_chunk(
            plan,
            options.chunk_id,
            report["fingerprint"],
            plan.get("schema_version", SCHEMA_VERSION),
        )
        targets = chunk_ciks(rows, chunk)
        expected_ciks = plan.get("cik_padded", [])[chunk.start_row : chunk.end_row + 1]
        checkpoint_root = options.artifacts_dir
    else:
        if not 1 <= options.partition_id <= plan.get("partition_count", 1):
            raise ValueError(
                f"partition_id must be between 1 and {plan.get('partition_count', 1)}"
            )
        partition = next(
            (
                item
                for item in plan.get("partitions", [])
                if item["partition_id"] == options.partition_id
            ),
            None,
        )
        if partition is None:
            raise ValueError(
                f"partition {options.partition_id} is not present in plan.json"
            )
        chunk_info = next(
            (
                item
                for item in partition["chunks"]
                if item["chunk_id"] == options.chunk_id
            ),
            None,
        )
        if chunk_info is None:
            raise ValueError(
                f"chunk_id {options.chunk_id} is not present in partition {options.partition_id}"
            )
        from .chunks import ChunkRange

        chunk = ChunkRange(
            chunk_info["chunk_id"],
            chunk_info["start_row"],
            chunk_info["end_row"],
            chunk_info["first_cik"],
            chunk_info["last_cik"],
        )
        expected_ciks = partition["cik_padded"][chunk.start_row : chunk.end_row + 1]
        target_by_cik = {target.cik_padded: target for target in rows}
        targets = [target_by_cik[cik] for cik in expected_ciks if cik in target_by_cik]
        checkpoint_root = os.path.join(
            options.artifacts_dir, "partitions", f"partition-{options.partition_id:05d}"
        )
    if [t.cik_padded for t in targets] != expected_ciks:
        raise ValueError("chunk CIK assignment does not match plan order")

    store = make_checkpoint_store(
        options, input_fingerprint=report["fingerprint"], root=checkpoint_root
    )
    existing = store.find(chunk.chunk_id, chunk)
    if existing:
        logger.info(
            "chunk %d already complete at %s; nothing to do",
            chunk.chunk_id,
            existing.path,
        )
        return {
            "chunk_id": chunk.chunk_id,
            "skipped": True,
            "checkpoint": existing.path,
        }

    client = _build_client(options)
    snapshot_id = f"{options.run_id}-{chunk.chunk_id}"
    started = time.monotonic()
    results: dict[str, dict] = {}
    failures: list[str] = []

    def work(target):
        return target.cik_padded, _fetch_and_normalize(client, target, snapshot_id)

    def emit(event: dict) -> None:
        if progress is None:
            return
        try:
            progress(event)
        except Exception:
            logger.exception("progress callback failed")

    with ThreadPoolExecutor(max_workers=options.effective_workers()) as pool:
        futures = [pool.submit(work, target) for target in targets]
        for future in as_completed(futures):
            try:
                cik, row = future.result()
            except Exception as exc:
                failures.append(f"{type(exc).__name__}: {exc}")
                logger.exception("worker failed")
                emit(
                    {
                        "type": "worker_failed",
                        "chunk_id": chunk.chunk_id,
                        "error": f"{type(exc).__name__}: {exc}",
                        "metrics": client.http.metrics.snapshot(),
                    }
                )
                continue
            row["input_fingerprint"] = report["fingerprint"]
            row["chunk_id"] = chunk.chunk_id
            results[cik] = row
            emit(
                {
                    "type": "cik_done",
                    "chunk_id": chunk.chunk_id,
                    "cik": cik,
                    "status": row["status"],
                    "filings": len(row["filings"]),
                    "historical_files": row.get("historical_files_total", 0),
                    "metrics": client.http.metrics.snapshot(),
                }
            )

    # Every requested CIK gets one terminal row, including failed fetches.
    ordered_rows = []
    for target in targets:
        row = results.get(target.cik_padded)
        if row is None:
            row = normalize_submissions(
                {},
                cik_padded=target.cik_padded,
                input_name=target.name,
                snapshot_id=snapshot_id,
                fetched_at=utc_now_iso(),
                source_url=client.submissions_url(target.cik_padded),
                byte_count=0,
                historical_payloads=[],
                historical_errors=[
                    f"unhandled worker failure: {'; '.join(failures) or 'unknown'}"
                ],
                response_sha256="",
            )
            row["input_fingerprint"] = report["fingerprint"]
            row["chunk_id"] = chunk.chunk_id
        ordered_rows.append(row)

    if len(ordered_rows) != chunk.row_count:
        raise RuntimeError(
            f"refusing to write checkpoint: {len(ordered_rows)} rows != expected {chunk.row_count}"
        )
    checkpoint_ref = store.write(ordered_rows, chunk)
    elapsed = time.monotonic() - started
    summary = {
        "chunk_id": chunk.chunk_id,
        "skipped": False,
        "workers": options.effective_workers(),
        "rows": checkpoint_ref.row_count,
        "checkpoint": checkpoint_ref.path,
        "statuses": {
            status: sum(1 for row in ordered_rows if row["status"] == status)
            for status in {row["status"] for row in ordered_rows}
        },
        "filings": sum(len(row["filings"]) for row in ordered_rows),
        "elapsed_s": round(elapsed, 2),
        "metrics": client.http.metrics.snapshot(),
    }
    logger.info(
        "chunk %d complete: %s", chunk.chunk_id, json.dumps(summary["statuses"])
    )
    return summary


def run_partition(options: RunOptions, partition_id: int, progress=None) -> dict:
    """Run every missing chunk in one operational partition."""
    plan = load_plan(options)
    partition = next(
        (
            item
            for item in plan.get("partitions", [])
            if item["partition_id"] == partition_id
        ),
        None,
    )
    if partition is None:
        raise ValueError(f"partition {partition_id} is not present in plan.json")
    summaries = []
    for chunk in partition.get("chunks", []):
        summaries.append(
            run_chunk(
                replace(options, partition_id=partition_id, chunk_id=chunk["chunk_id"]),
                progress=progress,
            )
        )
    return {
        "partition_id": partition_id,
        "workers": options.effective_workers(),
        "chunk_count": len(summaries),
        "chunks": summaries,
        "rows": sum(summary.get("rows", 0) for summary in summaries),
        "skipped_chunks": sum(summary.get("skipped", False) for summary in summaries),
    }


def get_status(options: RunOptions, partition_id: int | None = None) -> dict:
    """`status`: report input fingerprint, schema version, chunk ranges,
    completed/failed CIK counts, retryable errors, and mergeability."""
    plan = load_plan(options)
    storage_format = plan.get("storage_format", options.storage_format)
    scope = plan
    root = options.artifacts_dir
    if partition_id is not None:
        scope = next(
            (
                item
                for item in plan.get("partitions", [])
                if item["partition_id"] == partition_id
            ),
            None,
        )
        if scope is None:
            raise ValueError(f"partition {partition_id} is not present in plan.json")
        root = os.path.join(
            options.artifacts_dir, "partitions", f"partition-{partition_id:05d}"
        )
    store = make_phase_store(
        storage_format,
        root,
        options.run_id,
        plan.get("input_fingerprint", ""),
    )
    refs = store.list()
    rows_by_chunk = {ref.chunk_id: store.load(ref.chunk_id) for ref in refs}
    from collections import Counter

    statuses = [row["status"] for rows in rows_by_chunk.values() for row in rows]
    summary = {
        "chunk_files": len(refs),
        "rows_total": sum(map(len, rows_by_chunk.values())),
        "unique_ciks": len(
            {row["cik"] for rows in rows_by_chunk.values() for row in rows}
        ),
        "status_counts": dict(Counter(statuses)),
        "filings_total": sum(
            len(row.get("filings") or [])
            for rows in rows_by_chunk.values()
            for row in rows
        ),
        "historical_file_failures": sum(
            row.get("historical_files_failed") or 0
            for rows in rows_by_chunk.values()
            for row in rows
        ),
        "non_terminal_rows": sum(
            status not in TERMINAL_STATUSES for status in statuses
        ),
    }
    summary["mergeable"] = (
        summary["rows_total"] > 0 and summary["non_terminal_rows"] == 0
    )
    completed_chunks = {ref.chunk_id for ref in refs}
    all_chunk_ids = [chunk["chunk_id"] for chunk in scope.get("chunks", [])]
    missing = [cid for cid in all_chunk_ids if cid not in completed_chunks]
    status = {
        "artifacts_dir": options.artifacts_dir,
        "schema_version": plan.get("schema_version"),
        "input_fingerprint": plan.get("input_fingerprint"),
        "plan_hash": plan.get("plan_hash"),
        "chunk_count": len(all_chunk_ids),
        "partition_id": partition_id,
        "completed_chunks": len(completed_chunks),
        "missing_chunks": missing,
        **summary,
        "mergeable": not missing and summary.get("mergeable", False),
    }
    return status


def merge(
    options: RunOptions,
    output_path: str | None = None,
    *,
    storage_format: str | None = None,
    output_storage_format: str | None = None,
    progress=None,
) -> MergeReport:
    """`merge`: combine published partitions into the final dataset."""
    if options.augmentation:
        _root, delta_path, default_full_path, _snapshot_path = output_paths(options)
        delta_report = merge_partition_artifacts(
            options.artifacts_dir,
            str(delta_path),
            storage_format=storage_format,
            output_storage_format=output_storage_format,
            progress=progress,
        )
        if output_path is not None:
            requested = Path(output_path).resolve()
            if requested != default_full_path.resolve():
                default_full_path = requested
        return publish_snapshot(
            options,
            delta_report,
            delta_path,
            full_path_override=Path(output_path).resolve()
            if output_path is not None
            else None,
        )
    if output_path is None:
        artifact_root = Path(options.artifacts_dir).resolve()
        marker = f"{os.sep}transient{os.sep}"
        root = (
            Path(str(artifact_root).split(marker, 1)[0])
            if marker in str(artifact_root)
            else artifact_root.parent
        )
        output_path = str(
            resolve_paths(env={"ARTIFACTS_ROOT": str(root)}).published_dataset_path(
                "metadata", "submission_metadata", "parquet"
            )
        )
    return merge_partition_artifacts(
        options.artifacts_dir,
        output_path,
        storage_format=storage_format,
        output_storage_format=output_storage_format,
        progress=progress,
    )


def merge_one_partition(
    options: RunOptions,
    partition_id: int,
    *,
    output_path: str | None = None,
    storage_format: str | None = None,
    output_storage_format: str | None = None,
    progress=None,
) -> MergeReport:
    """`merge-partition`: publish one complete partition artifact."""
    return merge_partition(
        options.artifacts_dir,
        partition_id,
        output_path=output_path,
        storage_format=storage_format or options.storage_format,
        output_storage_format=output_storage_format,
        progress=progress,
    )


__all__ = [
    "MergeError",
    "build_plan",
    "get_status",
    "load_plan",
    "merge",
    "merge_one_partition",
    "preview_sample",
    "run_chunk",
    "run_partition",
]
