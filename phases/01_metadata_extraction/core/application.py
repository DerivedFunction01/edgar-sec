"""Orchestration functions exposed by the barrel: build_plan, preview_sample,
run_chunk, get_status, merge_chunks. Entry points must import from here and
must not duplicate fetching, normalization, or checkpoint logic."""

from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from .checkpoints import (
    chunk_filename,
    find_chunk_checkpoint,
    list_chunk_checkpoints,
    summarize_checkpoints,
    write_checkpoint,
)
from .chunks import (
    assign_chunks,
    chunk_ciks,
    plan_hash,
    select_chunk,
    verify_chunk_assignment,
)
from .config import RunOptions, rate_limit_to_interval
from .input_manifest import read_input_manifest
from .merge import MergeError, MergeReport, merge_chunks
from .normalize import normalize_submissions
from .schemas import SCHEMA_VERSION
from .sec_client import SubmissionsClient

logger = logging.getLogger("metadata")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_plan(options: RunOptions) -> dict:
    """`plan`: read and validate the CSV, normalize CIKs to ten digits,
    sort deterministically, assign contiguous chunk ranges, and write
    plan.json. Performs no SEC requests."""
    rows, report = read_input_manifest(options.input_path, limit=options.limit)
    ciks = [row.cik_padded for row in rows]
    chunks = assign_chunks(ciks, options.chunk_size)
    verify_chunk_assignment(rows, chunks)

    plan = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "input_path": options.input_path,
        "input_fingerprint": report["fingerprint"],
        "row_count": len(rows),
        "chunk_size": options.chunk_size,
        "malformed": report["malformed"],
        "duplicates": report["duplicates"],
        "cik_padded": ciks,
        "chunks": [chunk.to_dict() for chunk in chunks],
    }
    plan["plan_hash"] = plan_hash(plan)

    os.makedirs(options.artifacts_dir, exist_ok=True)
    plan_path = os.path.join(options.artifacts_dir, "plan.json")
    with open(plan_path, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2, sort_keys=True)

    logger.info(
        "plan: %d CIKs, %d chunks, %d malformed, %d duplicates -> %s",
        len(rows),
        len(chunks),
        len(report["malformed"]),
        len(report["duplicates"]),
        plan_path,
    )
    return plan


def load_plan(options: RunOptions) -> dict:
    path = os.path.join(options.artifacts_dir, "plan.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"plan.json not found in {options.artifacts_dir}; run `plan` first")
    with open(path, "r", encoding="utf-8") as fh:
        plan = json.load(fh)
    expected = plan.get("plan_hash")
    if expected and plan_hash(plan) != expected:
        raise ValueError("plan.json hash mismatch: the manifest was modified after creation")
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
    rows, _report = read_input_manifest(options.input_path, limit=max(sample_size, options.limit or 0))
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
        json.dump({"sample": summaries, "metrics": client.http.metrics.snapshot()}, fh, indent=2)

    parquet_rows = [row for row in completed_rows if row.get("status") != "failed"]
    if parquet_rows:
        import pyarrow as pa
        import pyarrow.parquet as pq

        from .schemas import SUBMISSION_METADATA_SCHEMA

        table = pa.Table.from_pylist(parquet_rows, schema=SUBMISSION_METADATA_SCHEMA)
        pq.write_table(table, os.path.join(options.artifacts_dir, "preview_sample.parquet"))

    for item in summaries:
        print(
            f"{item['cik']}  {str(item.get('sec_name') or item.get('input_name'))[:40]:40s} "
            f"status={item['status']} filings={item.get('combined_filing_records', 0)} "
            f"hist_files={item.get('historical_files', 0)}"
            + (f" error={item['error']}" if item.get("error") else "")
        )
    return {"sample": summaries, "metrics": client.http.metrics.snapshot(), "summary_path": out_json}


def run_chunk(options: RunOptions) -> dict:
    """`run`: process exactly one chunk-id from the matching plan.json.

    Fetches each assigned CIK, follows every historical submissions file,
    combines all filing records into the CIK's nested filings list, and
    writes a validated atomic checkpoint. Resumes from a valid completed
    checkpoint, never from an in-memory counter."""
    plan = load_plan(options)
    if options.chunk_id is None:
        raise ValueError("--chunk-id is required for run")

    rows, report = read_input_manifest(options.input_path, limit=options.limit)
    if report["fingerprint"] != plan.get("input_fingerprint"):
        raise ValueError(
            "input fingerprint mismatch between CSV and plan.json; regenerate the plan"
        )
    chunk = select_chunk(plan, options.chunk_id, report["fingerprint"], plan.get("schema_version", SCHEMA_VERSION))
    targets = chunk_ciks(rows, chunk)
    if [t.cik_padded for t in targets] != plan.get("cik_padded", [])[chunk.start_row : chunk.end_row + 1]:
        raise ValueError("chunk CIK assignment does not match plan order")

    chunks_dir = os.path.join(options.artifacts_dir, "chunks")
    final_path = os.path.join(chunks_dir, chunk_filename(chunk.chunk_id, chunk.start_row, chunk.end_row))
    existing = find_chunk_checkpoint(chunks_dir, chunk.chunk_id, plan.get("schema_version"))
    if existing:
        logger.info("chunk %d already complete at %s; nothing to do", chunk.chunk_id, existing)
        return {"chunk_id": chunk.chunk_id, "skipped": True, "checkpoint": existing}

    client = _build_client(options)
    snapshot_id = f"{options.run_id}-{chunk.chunk_id}"
    started = time.monotonic()
    results: dict[str, dict] = {}
    failures: list[str] = []

    def work(target):
        return target.cik_padded, _fetch_and_normalize(client, target, snapshot_id)

    with ThreadPoolExecutor(max_workers=options.workers) as pool:
        futures = [pool.submit(work, target) for target in targets]
        for future in as_completed(futures):
            try:
                cik, row = future.result()
            except Exception as exc:
                failures.append(f"{type(exc).__name__}: {exc}")
                logger.exception("worker failed")
                continue
            row["input_fingerprint"] = report["fingerprint"]
            row["chunk_id"] = chunk.chunk_id
            results[cik] = row

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
                historical_errors=[f"unhandled worker failure: {'; '.join(failures) or 'unknown'}"],
                response_sha256="",
            )
            row["input_fingerprint"] = report["fingerprint"]
            row["chunk_id"] = chunk.chunk_id
        ordered_rows.append(row)

    if len(ordered_rows) != chunk.row_count:
        raise RuntimeError(
            f"refusing to write checkpoint: {len(ordered_rows)} rows != expected {chunk.row_count}"
        )
    checkpoint_info = write_checkpoint(ordered_rows, final_path)
    elapsed = time.monotonic() - started
    summary = {
        "chunk_id": chunk.chunk_id,
        "skipped": False,
        "rows": checkpoint_info["rows"],
        "checkpoint": checkpoint_info["path"],
        "statuses": {
            status: sum(1 for row in ordered_rows if row["status"] == status)
            for status in {row["status"] for row in ordered_rows}
        },
        "filings": sum(len(row["filings"]) for row in ordered_rows),
        "elapsed_s": round(elapsed, 2),
        "metrics": client.http.metrics.snapshot(),
    }
    logger.info("chunk %d complete: %s", chunk.chunk_id, json.dumps(summary["statuses"]))
    return summary


def get_status(options: RunOptions) -> dict:
    """`status`: report input fingerprint, schema version, chunk ranges,
    completed/failed CIK counts, retryable errors, and mergeability."""
    plan = load_plan(options)
    chunks_dir = os.path.join(options.artifacts_dir, "chunks")
    summary = summarize_checkpoints(chunks_dir)
    completed_chunks = {info["chunk_id"] for info in list_chunk_checkpoints(chunks_dir)}
    all_chunk_ids = [chunk["chunk_id"] for chunk in plan.get("chunks", [])]
    missing = [cid for cid in all_chunk_ids if cid not in completed_chunks]
    status = {
        "artifacts_dir": options.artifacts_dir,
        "schema_version": plan.get("schema_version"),
        "input_fingerprint": plan.get("input_fingerprint"),
        "plan_hash": plan.get("plan_hash"),
        "chunk_count": len(all_chunk_ids),
        "completed_chunks": len(completed_chunks),
        "missing_chunks": missing,
        **summary,
        "mergeable": not missing and summary.get("mergeable", False),
    }
    return status


def merge(options: RunOptions, output_path: str, *, allow_accession_duplicates: bool = False) -> MergeReport:
    """`merge`: accept only finalized checkpoints for the same fingerprint
    and schema version, verify the contract, then write the unified dataset."""
    return merge_chunks(
        options.artifacts_dir,
        output_path,
        allow_accession_duplicates=allow_accession_duplicates,
    )


__all__ = [
    "MergeError",
    "build_plan",
    "get_status",
    "load_plan",
    "merge",
    "preview_sample",
    "run_chunk",
]
