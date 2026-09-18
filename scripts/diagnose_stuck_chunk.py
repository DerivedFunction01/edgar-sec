"""Profile unfinished Phase 025 documents from one chunk.

Run from the repository root on the acquisition machine, for example:

    python scripts/diagnose_stuck_chunk.py \
      --chunk-db .artifacts/transient/webpage_storage/runs/local/workers/worker-00023/attempt-00001/chunk-00023.db \
      --cache-dir .artifacts/caches \
      --timeout 180

Each candidate is processed in a fresh subprocess.  A bad document therefore
cannot contaminate the next candidate or the diagnostic parent process.
"""

from __future__ import annotations

import argparse
import cProfile
import gc
import importlib
import json
import pstats
import re
import resource
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from tqdm import tqdm

_TABLE_RE = re.compile(r"<table\b", re.IGNORECASE)
_HTML_RE = re.compile(r"<\s*(?:html|table|div|span|p|body|tr|td)\b", re.IGNORECASE)


def _rss_mib() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def _run_root(chunk_db: Path) -> Path:
    # .../runs/<run-id>/workers/<worker>/attempt/<chunk>.db
    return chunk_db.resolve().parents[3]


def _load_run_metadata(chunk_db: Path) -> dict:
    path = _run_root(chunk_db) / "run_metadata.json"
    if not path.is_file():
        raise FileNotFoundError(f"run metadata not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _chunk_rows(chunk_db: Path) -> tuple[set[str], set[str]]:
    con = sqlite3.connect(f"file:{chunk_db}?mode=ro", uri=True)
    try:
        blobs = {row[0] for row in con.execute("SELECT doc_id FROM document_blobs")}
        failures = {
            row[0] for row in con.execute("SELECT doc_id FROM acquisition_failures")
        }
        return blobs, failures
    finally:
        con.close()


def _document_id(locator) -> str:
    schemas = importlib.import_module("phases.025_webpage_storage.core.schemas")
    return schemas.doc_id(locator.accession, locator.document_path)


def _profile_one(args: argparse.Namespace) -> int:
    schemas = importlib.import_module("phases.025_webpage_storage.core.schemas")
    cache_module = importlib.import_module("defs.sec_http.cache")
    processors = importlib.import_module("phases.025_webpage_storage.processors")

    locator = schemas.DocumentLocator(
        locator_key=args.locator_key,
        accession=args.accession,
        document_path=args.document_path,
        archive_url=args.archive_url,
        form=args.form,
    )
    cache = cache_module.SqlCacheReader(args.cache_dir)
    raw = cache.get(locator.archive_url)
    if raw is None:
        print(json.dumps({"status": "cache-miss"}), flush=True)
        return 3

    decoded_prefix = raw[:1_000_000].decode("latin-1", errors="replace")
    result: dict[str, object] = {
        "status": "started",
        "locator_key": locator.locator_key,
        "accession": locator.accession,
        "document_path": locator.document_path,
        "input_bytes": len(raw),
        "table_tags": len(_TABLE_RE.findall(decoded_prefix)),
        "html_like": bool(_HTML_RE.search(decoded_prefix)),
        "rss_before_mib": _rss_mib(),
    }
    profiler = cProfile.Profile()
    started = time.monotonic()
    try:
        profiler.enable()
        processor = processors.DefaultFilingProcessor()
        import asyncio

        processed = asyncio.run(processor.process(raw, locator))
        profiler.disable()
        result.update(
            {
                "status": "ok",
                "output_bytes": len(processed.payload),
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "rss_after_mib": round(_rss_mib(), 1),
            }
        )
    except Exception as exc:  # noqa: BLE001 - isolate each diagnostic subprocess
        profiler.disable()
        result.update(
            {
                "status": "error",
                "error_type": type(exc).__name__,
                "error": str(exc)[:1000],
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "rss_after_mib": round(_rss_mib(), 1),
            }
        )
    finally:
        cache.close()
        gc.collect()

    if args.profile:
        stats = pstats.Stats(profiler).sort_stats("cumulative")
        stats.dump_stats(args.profile)
        result["profile"] = args.profile
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0 if result["status"] == "ok" else 2


def _profile_candidates(args: argparse.Namespace) -> int:
    chunk_db = Path(args.chunk_db).resolve()
    metadata = _load_run_metadata(chunk_db)
    plan_dir = Path(metadata["plan_dir"])
    if not plan_dir.is_absolute():
        plan_dir = (Path.cwd() / plan_dir).resolve()

    targets = importlib.import_module("phases.025_webpage_storage.core.targets")
    locators, _occurrences, _plan = targets.load_targets(plan_dir)
    selected = targets.partition_locators(
        locators,
        int(metadata.get("partition_id", 1)),
        int(metadata.get("partition_count", 1)),
    )
    chunk_id = chunk_db.stem
    try:
        chunk_number = int(chunk_id.rsplit("-", 1)[1])
    except (IndexError, ValueError) as exc:
        raise ValueError(f"cannot parse chunk number from {chunk_id}") from exc
    chunk_size = int(metadata["chunk_size"])
    start = (chunk_number - 1) * chunk_size
    chunk_locators = selected[start : start + chunk_size]

    completed, failures = _chunk_rows(chunk_db)
    candidates = [
        locator
        for locator in chunk_locators
        if _document_id(locator) not in completed | failures
    ]
    if args.limit > 0:
        candidates = candidates[: args.limit]
    print(
        json.dumps(
            {
                "chunk": chunk_id,
                "chunk_locators": len(chunk_locators),
                "completed_blobs": len(completed),
                "recorded_failures": len(failures),
                "unfinished_locators": len(candidates),
                "chunk_committed": False,
            },
            sort_keys=True,
        ),
        flush=True,
    )

    report_path = Path(args.report or f"stuck-{chunk_id}-diagnostics.jsonl")
    with report_path.open("w", encoding="utf-8") as report:
        for index, locator in enumerate(
            tqdm(candidates, desc=f"Profiling {chunk_id}", unit="doc"), 1
        ):
            profile_path = None
            if args.profile_dir:
                profile_dir = Path(args.profile_dir)
                profile_dir.mkdir(parents=True, exist_ok=True)
                profile_path = str(
                    profile_dir / f"{index:05d}-{_document_id(locator)}.prof"
                )
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--single",
                "--cache-dir",
                args.cache_dir,
                "--locator-key",
                locator.locator_key,
                "--accession",
                locator.accession,
                "--document-path",
                locator.document_path,
                "--archive-url",
                locator.archive_url,
                "--form",
                locator.form,
            ]
            if profile_path:
                command.extend(("--profile", profile_path))
            started_record = {
                "status": "started",
                "index": index,
                "locator_key": locator.locator_key,
                "accession": locator.accession,
                "document_path": locator.document_path,
                "archive_url": locator.archive_url,
                "profile": profile_path,
            }
            report.write(json.dumps(started_record, sort_keys=True) + "\n")
            report.flush()
            print(json.dumps(started_record, sort_keys=True), flush=True)
            started = time.monotonic()
            try:
                completed_run = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=args.timeout,
                    check=False,
                )
                output = completed_run.stdout.strip().splitlines()
                result = (
                    json.loads(output[-1])
                    if output
                    else {
                        "status": "no-output",
                        "stderr": completed_run.stderr[-2000:],
                    }
                )
                result["returncode"] = completed_run.returncode
            except subprocess.TimeoutExpired:
                result = {
                    "status": "timeout",
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                }
            result.update(
                {
                    "index": index,
                    "locator_key": locator.locator_key,
                    "accession": locator.accession,
                    "document_path": locator.document_path,
                    "archive_url": locator.archive_url,
                }
            )
            report.write(json.dumps(result, sort_keys=True) + "\n")
            report.flush()
            if result["status"] in {"timeout", "error"}:
                print(json.dumps(result, sort_keys=True), flush=True)
    print(f"diagnostics written to {report_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunk-db")
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--report")
    parser.add_argument("--profile-dir")
    parser.add_argument("--single", action="store_true")
    parser.add_argument("--profile")
    parser.add_argument("--locator-key")
    parser.add_argument("--accession")
    parser.add_argument("--document-path")
    parser.add_argument("--archive-url")
    parser.add_argument("--form", default="")
    args = parser.parse_args()
    if args.single:
        return _profile_one(args)
    if not args.chunk_db:
        parser.error("--chunk-db is required unless --single is used")
    return _profile_candidates(args)


if __name__ == "__main__":
    raise SystemExit(main())
