#!/usr/bin/env python3
"""Live progress monitor for Phase 2.5 Webpage Storage runs.

Polls active worker SQLite databases in read-only mode to display real-time
ingestion counts, database disk usage, rolling throughput (docs/s), tqdm progress,
estimated time to completion (ETA), and per-chunk worker status.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from collections import deque
from collections.abc import Sequence
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tqdm import tqdm

from defs.runtime.paths import resolve_paths
from defs.runtime.settings import get_setting
from defs.sec_http.broker_cli import _broker_paths, _read_registry, _socket_alive
from defs.sql import (
    Aggregate,
    AggregateFunction,
    Select,
    SqlDialect,
    Star,
    Table,
    make_sql_executor,
)


def _safe_count(executor, table_name: str) -> int:
    """Safely count rows in a table using compiled SQL."""
    try:
        query = Select(
            source=Table(table_name),
            projection=(Aggregate(AggregateFunction.COUNT, Star()),),
        )
        row = executor.query_one(executor.compiler.compile(query))
        if row and len(row) > 0:
            val = next(iter(row.values()))
            return int(val) if val is not None else 0
    except Exception:
        return 0
    return 0


def _get_chunk_stats(db_path: Path) -> dict[str, int | str | bool]:
    """Inspect one chunk SQLite database in read-only mode."""
    stats: dict[str, int | str | bool] = {
        "path": str(db_path),
        "chunk_id": db_path.stem,
        "worker": db_path.parent.parent.name,
        "size_bytes": 0,
        "blobs": 0,
        "normalized": 0,
        "failures": 0,
        "committed": False,
    }

    # Sum total bytes of .db, .db-wal, and .db-shm files
    for ext in ("", "-wal", "-shm"):
        sidecar = Path(str(db_path) + ext)
        if sidecar.is_file():
            try:
                stats["size_bytes"] = int(stats["size_bytes"]) + sidecar.stat().st_size
            except OSError:
                pass

    if not db_path.is_file():
        return stats

    try:
        executor = make_sql_executor(db_path, dialect=SqlDialect.SQLITE)
        try:
            stats["blobs"] = _safe_count(executor, "document_blobs")
            stats["normalized"] = _safe_count(executor, "normalized_documents")
            stats["failures"] = _safe_count(executor, "acquisition_failures")
            stats["committed"] = _safe_count(executor, "_committed_chunks") > 0
        finally:
            executor.close()
    except Exception:
        return stats

    return stats


def _find_chunk_dbs(
    artifacts_root: Path | None = None, run_id: str | None = None
) -> list[Path]:
    """Find all chunk databases under transient webpage_storage runs."""
    env = {"ARTIFACTS_ROOT": str(artifacts_root)} if artifacts_root else None
    if run_id:
        w_root = resolve_paths("webpage_storage", run_id, env=env).workers_root
        return (
            [
                m
                for m in sorted(w_root.rglob("*.db"))
                if m.is_file() and m.name.startswith("chunk-")
            ]
            if w_root.exists()
            else []
        )

    base = resolve_paths("webpage_storage", env=env).runs_root
    return (
        [
            m
            for m in sorted(base.rglob("*.db"))
            if m.is_file() and m.name.startswith("chunk-")
        ]
        if base.exists()
        else []
    )


def _detect_run_id(chunk_paths: Sequence[Path]) -> str:
    """Extract active run ID from discovered chunk paths."""
    if not chunk_paths:
        return ""
    parts = chunk_paths[0].parts
    if "runs" in parts:
        idx = parts.index("runs")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return ""


def _inspect_run_metadata(
    artifacts_root: Path, run_id: str | None = None
) -> tuple[dict | None, str]:
    """Inspect run_metadata.json from active or specified transient run."""
    env = {"ARTIFACTS_ROOT": str(artifacts_root)} if artifacts_root else None
    runs_dir = resolve_paths("webpage_storage", env=env).runs_root
    if not runs_dir.is_dir():
        return None, run_id or ""

    if run_id:
        meta_file = runs_dir / run_id / "run_metadata.json"
        if meta_file.is_file():
            with suppress(Exception), open(meta_file, encoding="utf-8") as f:
                return json.load(f), run_id
        return None, run_id

    candidates = sorted(
        runs_dir.iterdir(),
        key=lambda p: (
            (p / "run_metadata.json").stat().st_mtime
            if (p / "run_metadata.json").is_file()
            else p.stat().st_mtime
            if p.exists()
            else 0
        ),
        reverse=True,
    )
    for r_dir in candidates:
        if not r_dir.is_dir():
            continue
        meta_file = r_dir / "run_metadata.json"
        if meta_file.is_file():
            with suppress(Exception), open(meta_file, encoding="utf-8") as f:
                return json.load(f), r_dir.name
        if (r_dir / "workers").is_dir():
            return None, r_dir.name
    return None, ""


def _discover_target_plan(
    artifacts_root: Path, run_id: str | None = None
) -> tuple[int | None, str | None, str | None]:
    """Discover total planned documents, plan ID, and scope from target plans."""
    env = {"ARTIFACTS_ROOT": str(artifacts_root)} if artifacts_root else None
    plans_dir = resolve_paths(env=env).dataset_manifests(
        "filing_extraction", "target_plans"
    )
    if not plans_dir.is_dir():
        return None, None, None

    for plan_path in sorted(
        plans_dir.iterdir(),
        key=lambda p: p.stat().st_mtime if p.exists() else 0,
        reverse=True,
    ):
        if not plan_path.is_dir() or (
            run_id and run_id != "local" and plan_path.name != run_id
        ):
            continue
        plan_file = plan_path / "plan.json"
        if plan_file.is_file():
            with suppress(Exception), open(plan_file, encoding="utf-8") as f:
                data = json.load(f)
            total = data.get("active_targets_count") or data.get("selected_rows")
            if total and int(total) > 0:
                return int(total), plan_path.name, str(data.get("scope", "full"))
    return None, None, None


def _format_size(num_bytes: int) -> str:
    """Format bytes into human-readable units."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:3.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} PB"


def _format_duration(seconds: float) -> str:
    """Format seconds into human-readable duration (e.g. 14h 22m 10s)."""
    if seconds < 0 or math.isnan(seconds):
        return "--"
    secs = round(seconds)
    hrs, remainder = divmod(secs, 3600)
    mins, s = divmod(remainder, 60)
    if hrs > 0:
        return f"{hrs}h {mins:02d}m {s:02d}s"
    if mins > 0:
        return f"{mins}m {s:02d}s"
    return f"{s}s"


def render_dashboard(
    chunk_stats: Sequence[dict[str, int | str | bool]],
    history: deque[tuple[float, int]],
    start_time: float,
    total_target_docs: int | None = None,
    plan_id: str | None = None,
    plan_scope: str | None = None,
    run_id: str = "",
    mode: str | None = None,
    window_s: float = 60.0,
) -> None:
    """Print an updated monitoring dashboard with rolling speed and tqdm progress bar."""
    now = time.monotonic()
    total_blobs = sum(int(s["blobs"]) for s in chunk_stats)
    total_normalized = sum(int(s["normalized"]) for s in chunk_stats)
    total_failures = sum(int(s["failures"]) for s in chunk_stats)
    total_bytes = sum(int(s["size_bytes"]) for s in chunk_stats)
    committed_chunks = sum(1 for s in chunk_stats if s["committed"])
    active_chunks = sum(1 for s in chunk_stats if not s["committed"])

    current_docs = total_blobs + total_failures

    # Record current observation in rolling history
    history.append((now, current_docs))
    cutoff = now - window_s
    while len(history) > 2 and history[0][0] < cutoff:
        history.popleft()

    # Calculate rolling speed
    rps = 0.0
    rps_str = "--"
    if len(history) >= 2:
        dt = history[-1][0] - history[0][0]
        dd = history[-1][1] - history[0][1]
        if dt >= 1.0:
            rps = dd / dt
            rps_str = f"{rps:.2f} docs/s"

    # Broker status check
    broker_status_str = "Unknown"
    try:
        b_paths = _broker_paths(None)
        if _socket_alive(b_paths):
            reg = _read_registry(b_paths) or {}
            cfg_rps = get_setting("sec.rate_limit_rps") or 7.0
            broker_status_str = f"\033[1;32mActive\033[0m (PID: {reg.get('pid', '?')}, Cap: {cfg_rps} RPS)"
        else:
            broker_status_str = "\033[1;33mInactive / Fixture Mode\033[0m"
    except Exception:
        broker_status_str = "Offline"

    term_width = 80
    try:
        term_width = os.get_terminal_size().columns
    except OSError:
        pass

    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    print("\033[2J\033[H", end="")  # Clear screen and move cursor to top
    print("=" * term_width)
    print(f" 🚀 SEC EDGAR Webpage Storage — Live Progress Monitor    [{ts}]")
    if mode:
        print(f" Execution Mode: \033[1;33m{mode}\033[0m")
    if plan_id:
        target_info = f" Target Plan   : \033[1;36m{plan_id}\033[0m"
        if total_target_docs:
            target_info += f" ({total_target_docs:,} total filings)"
        if plan_scope:
            target_info += f" [Scope: {plan_scope}]"
        print(target_info)
    if run_id:
        print(
            f" Active Run ID : {run_id} ({active_chunks + committed_chunks} chunk DBs)"
        )
    print(f" Broker Daemon : {broker_status_str}")
    print("=" * term_width)

    # Summary KPI Box
    print(f" 📁 Total Disk Usage  : \033[1;32m{_format_size(total_bytes)}\033[0m")
    print(
        f" 📄 Document Blobs    : \033[1;36m{total_blobs:,}\033[0m (Normalized: {total_normalized:,})"
    )
    print(f" ⚠️  Failures / 404s   : \033[1;33m{total_failures:,}\033[0m")
    print(
        f" 🧩 Chunks Progress   : \033[1;35m{committed_chunks} committed\033[0m, {active_chunks} active (Total: {len(chunk_stats)})"
    )
    print(
        f" ⚡ Rolling Speed     : \033[1;32m{rps_str}\033[0m ({int(window_s)}s moving avg)"
    )

    # Progress Bar & ETA
    if total_target_docs and total_target_docs > 0:
        elapsed = max(0.0, now - start_time)
        if rps > 0:
            bar_str = tqdm.format_meter(
                n=current_docs,
                total=total_target_docs,
                elapsed=elapsed,
                rate=rps,
                unit="docs",
                ncols=min(term_width - 4, 100),
            )
        else:
            bar_str = tqdm.format_meter(
                n=current_docs,
                total=total_target_docs,
                elapsed=0,
                unit="docs",
                ncols=min(term_width - 4, 100),
                bar_format="{percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} [{unit}]",
            )
        print("-" * term_width)
        print(f" 📊 {bar_str}")

        if rps > 0 and current_docs < total_target_docs:
            remaining_docs = total_target_docs - current_docs
            rem_secs = remaining_docs / rps
            est_completion = (datetime.now(UTC) + timedelta(seconds=rem_secs)).strftime(
                "%H:%M:%S UTC"
            )
            print(
                f" ⏱️  Estimated Time   : \033[1;36m{_format_duration(rem_secs)}\033[0m remaining [Est. completion: {est_completion}]"
            )
        elif current_docs >= total_target_docs:
            print(" 🎉 Target filings 100% completed!")

    print("-" * term_width)

    # Active Chunks Detail Table
    print(
        f" {'Chunk ID':<14} {'Worker':<16} {'Blobs':<10} {'Failures':<10} {'Disk Size':<12} {'Status'}"
    )
    print("-" * term_width)

    # Show top 15 active/recent chunks
    sorted_chunks = sorted(
        chunk_stats,
        key=lambda s: (not s["committed"], int(s["blobs"])),
        reverse=True,
    )

    for s in sorted_chunks[:15]:
        status_tag = (
            "\033[32m[COMMITTED]\033[0m"
            if s["committed"]
            else "\033[33m[WRITING]\033[0m"
        )
        print(
            f" {s['chunk_id']:<14} {s['worker']:<16} {s['blobs']:<10} {s['failures']:<10} {_format_size(int(s['size_bytes'])):<12} {status_tag}"
        )

    if len(sorted_chunks) > 15:
        print(f" ... and {len(sorted_chunks) - 15} more chunk databases.")

    print("=" * term_width)
    print(" (Press Ctrl+C to stop monitoring — does not interrupt pipeline)")
    sys.stdout.flush()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Live monitor for Webpage Storage SQLite chunks."
    )
    parser.add_argument(
        "--artifacts-root",
        default=None,
        help="Path to artifacts root (defaults to configured .artifacts)",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Specific run ID to monitor",
    )
    parser.add_argument(
        "--total-docs",
        type=int,
        default=None,
        help="Total target document count (auto-discovered from plan.json by default)",
    )
    parser.add_argument(
        "--window",
        type=float,
        default=60.0,
        help="Rolling average speed window in seconds (default: 60.0s)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="Polling interval in seconds (default: 2.0s)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Print a single snapshot and exit",
    )
    args = parser.parse_args()

    artifacts_root = (
        Path(args.artifacts_root).resolve()
        if args.artifacts_root
        else Path(resolve_paths().artifacts_root).resolve()
    )

    # Discover run metadata directly from active run
    run_meta, detected_run_id = _inspect_run_metadata(artifacts_root, args.run_id)
    detected_run_id = args.run_id or detected_run_id or ""

    total_docs = args.total_docs
    discovered_plan_id = None
    discovered_scope = None
    exec_mode = None

    if run_meta:
        discovered_plan_id = run_meta.get("plan_id")
        discovered_scope = run_meta.get("scope")
        if total_docs is None:
            total_docs = run_meta.get("total_target_docs") or run_meta.get(
                "total_plan_docs"
            )
        raw_mode = str(run_meta.get("mode", "")).lower()
        if raw_mode == "fixture":
            exec_mode = "Fixture CAS Replay (Offline)"
        elif raw_mode == "production":
            exec_mode = "Live SEC Archive (Production)"

    # Fallback to target plans directory if no metadata was found
    if total_docs is None or discovered_plan_id is None:
        fallback_total, fallback_plan, fallback_scope = _discover_target_plan(
            artifacts_root, detected_run_id
        )
        if total_docs is None:
            total_docs = fallback_total
        if discovered_plan_id is None:
            discovered_plan_id = fallback_plan
        if discovered_scope is None:
            discovered_scope = fallback_scope

    history: deque[tuple[float, int]] = deque()
    start_time = time.monotonic()

    try:
        while True:
            chunk_paths = _find_chunk_dbs(artifacts_root, detected_run_id)
            if not detected_run_id:
                detected_run_id = _detect_run_id(chunk_paths)

            if not chunk_paths:
                ts = datetime.now(UTC).strftime("%H:%M:%S")
                print(
                    f"[{ts}] Waiting for chunk databases under {artifacts_root} ...",
                    end="\r",
                )
                sys.stdout.flush()
            else:
                stats = [_get_chunk_stats(p) for p in chunk_paths]
                render_dashboard(
                    chunk_stats=stats,
                    history=history,
                    start_time=start_time,
                    total_target_docs=total_docs,
                    plan_id=discovered_plan_id or detected_run_id,
                    plan_scope=discovered_scope,
                    run_id=detected_run_id,
                    mode=exec_mode,
                    window_s=args.window,
                )

            if args.once:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nMonitoring stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
