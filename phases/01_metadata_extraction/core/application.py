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

from .chunks import (
    assign_chunks,
    assign_partitions,
    chunk_ciks,
    plan_hash,
    select_chunk,
    verify_chunk_assignment,
)
from .config import RunOptions, rate_limit_to_interval, validate_plan_against_options
from .input_manifest import read_input_manifest
from .merge import (
    MergeError,
    MergeReport,
    merge_partition,
    merge_partition_artifacts,
)
from .normalize import normalize_submissions
from .schemas import SCHEMA_VERSION, TERMINAL_STATUSES
from .sec_client import SubmissionsClient
from .storage import make_checkpoint_store, make_phase_store

logger = logging.getLogger("metadata")


def utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_plan(options: RunOptions) -> dict:
    """`plan`: read and validate the CSV, normalize CIKs to ten digits,
    sort deterministically, assign contiguous chunk ranges, and write
    plan.json. Performs no SEC requests."""
    rows, report = read_input_manifest(options.input_path, limit=options.limit)
    ciks = [row.cik_padded for row in rows]
    chunks = assign_chunks(ciks, options.chunk_size)
    partitions = assign_partitions(ciks, options.partition_count, options.chunk_size)
    verify_chunk_assignment(rows, chunks)

    plan = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "input_path": options.input_path,
        "input_fingerprint": report["fingerprint"],
        "row_count": len(rows),
        "chunk_size": options.chunk_size,
        "partition_count": options.partition_count,
        "partition_assignment": "round_robin_v1",
        "storage_format": options.storage_format,
        "malformed": report["malformed"],
        "duplicates": report["duplicates"],
        "cik_padded": ciks,
        "chunks": [chunk.to_dict() for chunk in chunks],
        "partitions": [partition.to_dict() for partition in partitions],
        "run_options": {
            "input_path": options.input_path,
            "artifacts_dir": options.artifacts_dir,
            "chunk_size": options.chunk_size,
            "partition_count": options.partition_count,
            "limit": options.limit,
            "storage_format": options.storage_format,
        },
    }
    plan["plan_hash"] = plan_hash(plan)

    os.makedirs(options.artifacts_dir, exist_ok=True)
    plan_path = os.path.join(options.artifacts_dir, "plan.json")
    with open(plan_path, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2, sort_keys=True)

    partitions_dir = os.path.join(options.artifacts_dir, "partitions")
    os.makedirs(partitions_dir, exist_ok=True)
    for partition in partitions:
        partition_path = os.path.join(
            partitions_dir, f"partition-{partition.partition_id:05d}.json"
        )
        with open(partition_path, "w", encoding="utf-8") as fh:
            json.dump(partition.to_dict(), fh, indent=2, sort_keys=True)

    logger.info(
        "plan: %d CIKs, %d chunks, %d malformed, %d duplicates -> %s",
        len(rows),
        len(chunks),
        len(report["malformed"]),
        len(report["duplicates"]),
        plan_path,
    )
    return plan


def load_plan(options: RunOptions | None = None) -> dict:
    path = os.path.join(options.artifacts_dir if options else "", "plan.json")
    if not options:
        # Fallback for callers that only have a path; skip freshness validation.
        if not os.path.exists(path):
            raise FileNotFoundError(f"plan.json not found at {path}; run `plan` first")
        with open(path, "r", encoding="utf-8") as fh:
            plan = json.load(fh)
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
    with open(path, "r", encoding="utf-8") as fh:
        plan = json.load(fh)
    expected = plan.get("plan_hash")
    if expected and plan_hash(plan) != expected:
        raise ValueError(
            "plan.json hash mismatch: the manifest was modified after creation"
        )
    validate_plan_against_options(plan, options)
    return plan


def _build_client(options: RunOptions) -> SubmissionsClient:
    options.validate()
    limiter_interval = rate_limit_to_interval(options.rate_limit_rps)
    from defs.sec_http import RateLimiter, RetryPolicy

    return SubmissionsClient(
        user_agent=options.user_agent,
        rate_limiter=RateLimiter(min_interval_s=limiter_interval),
        retry_policy=RetryPolicy(max_retries=options.max_retries),
        timeout_s=options.timeout_s,
        cache_dir=options.cache_dir,
        max_failure_attempts=options.max_failure_attempts,
        ignore_failure_history=options.ignore_failure_history,
    )


def _fetch_and_normalize(client: SubmissionsClient, target, snapshot_id: str) -> dict:
    result = client.fetch_cik(target.cik_padded)
    if not result.fetched_ok:
        return normalize_submissions(
            {},
            cik_padded=target.cik_padded,
            input_name=target.name,
            snapshot_id=snapshot_id,
            fetched_at=utc_now_iso(),
            source_url=result.source_url,
            byte_count=0,
            historical_payloads=[],
            historical_errors=[result.terminal_error() or "unknown fetch failure"],
            response_sha256="",
        )
    row = normalize_submissions(
        result.payload,
        cik_padded=target.cik_padded,
        input_name=target.name,
        snapshot_id=snapshot_id,
        fetched_at=utc_now_iso(),
        source_url=result.source_url,
        byte_count=result.byte_count,
        historical_payloads=result.historical_payloads,
        historical_errors=result.historical_errors,
        response_sha256=result.response_sha256,
    )
    return row


def preview_sample(options: RunOptions, sample_size: int = 3) -> dict:
    """`preview`/smoke_test: small deterministic sample, SEC-backed, writing
    inspectable output under .artifacts/metadata/preview/<run-id>. Never
    writes to the production phase output."""
    rows, _report = read_input_manifest(
        options.input_path, limit=max(sample_size, options.limit or 0)
    )
    sample = rows[:sample_size]
    client = _build_client(options)
    snapshot_id = f"preview-{utc_now_iso()}"
    summaries = []
    completed_rows = []
    for target in sample:
        try:
            row = _fetch_and_normalize(client, target, snapshot_id)
            completed_rows.append(row)
            forms = sorted({f.get("form") for f in row["filings"] if f.get("form")})
            summaries.append(
                {
                    "cik": target.cik_padded,
                    "input_name": target.name,
                    "sec_name": row["identity"]["name"],
                    "status": row["status"],
                    "error": row["error"],
                    "recent_filings": sum(
                        1 for f in row["filings"] if f.get("source_section") == "recent"
                    ),
                    "historical_files": row["historical_files_total"],
                    "combined_filing_records": len(row["filings"]),
                    "forms_found": forms,
                    "anomalies": row["anomalies"],
                }
            )
        except Exception as exc:  # noqa: BLE001  # preview failures must be visible
            summaries.append(
                {
                    "cik": target.cik_padded,
                    "input_name": target.name,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    os.makedirs(options.artifacts_dir, exist_ok=True)
    out_json = os.path.join(options.artifacts_dir, "preview_summary.json")
    with open(out_json, "w", encoding="utf-8") as fh:
        json.dump(
            {"sample": summaries, "metrics": client.http.metrics.snapshot()},
            fh,
            indent=2,
        )

    output_rows = [row for row in completed_rows if row.get("status") != "failed"]
    if output_rows:
        sample_path = os.path.join(
            options.artifacts_dir, f"preview_sample.{options.storage_format}"
        )
        make_checkpoint_store(options, root=options.artifacts_dir).finalize(
            output_rows, sample_path
        )
        summaries_path_note = sample_path
    else:
        summaries_path_note = None

    for item in summaries:
        print(
            f"{item['cik']}  {str(item.get('sec_name') or item.get('input_name'))[:40]:40s} "
            f"status={item['status']} filings={item.get('combined_filing_records', 0)} "
            f"hist_files={item.get('historical_files', 0)}"
            + (f" error={item['error']}" if item.get("error") else "")
        )
    return {
        "sample": summaries,
        "metrics": client.http.metrics.snapshot(),
        "summary_path": out_json,
        "sample_artifact": summaries_path_note,
    }


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

    rows, report = read_input_manifest(options.input_path, limit=options.limit)
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

    with ThreadPoolExecutor(max_workers=options.workers) as pool:
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
    output_path: str,
    *,
    storage_format: str | None = None,
    output_storage_format: str | None = None,
    progress=None,
) -> MergeReport:
    """`merge`: combine complete partition artifacts into the final dataset."""
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
