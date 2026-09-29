"""Bounded live SEC smoke test. Not part of the pytest suite.

    .venv/bin/python -m edgar_sec.pipelines.metadata_sync.smoke_test \
        --input tests/fixtures/cik_sec_mini.csv \
        --sample-size 3 \
        --artifacts <preview-root>

This is the credential-gated, rate-limited live path. It always writes to an
explicit preview artifacts root and never touches a published snapshot or the
production ``current`` pointer, so running it cannot corrupt real output.

It is deliberately not collected by pytest: the default gate stays offline and
deterministic, and live verification is an explicit manual step. Exit code is
nonzero when any sampled CIK fails.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from edgar_sec.foundation.runtime.memory import reclaim
from edgar_sec.foundation.runtime.settings import resolve_runtime_settings
from edgar_sec.foundation.runtime.settings.runtime import DEFAULT_CHUNK_SIZE

from .manifest import read_cik_manifest
from .paths import resolve_run_paths
from .planner import build_plan, write_plan
from .roster import roster_from_manifest
from .sec_client import SubmissionsClient
from .worker import resolve_workers, run_chunk


def build_parser() -> argparse.ArgumentParser:
    """Build the smoke-test argument parser."""
    parser = argparse.ArgumentParser(
        prog="edgar_sec.pipelines.metadata_sync.smoke_test",
        description="Bounded live SEC smoke test (never publishes a snapshot)",
    )
    parser.add_argument("--input", required=True, help="CIK manifest CSV")
    parser.add_argument(
        "--artifacts",
        required=True,
        help="preview artifacts root; never a production snapshot root",
    )
    parser.add_argument("--sample-size", type=int, default=3)
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=None,
        help=f"CIKs per chunk (default: runtime.chunk_size, {DEFAULT_CHUNK_SIZE})",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="worker threads; machine-derived if unset",
    )
    return parser


def _build_client(artifacts_root: Path) -> SubmissionsClient:
    """Build the live client, caching inside the preview root only."""
    settings = resolve_runtime_settings()
    return SubmissionsClient(settings=settings.sec, cache_dir=str(artifacts_root))


def main(argv: list[str] | None = None) -> int:
    """Run a bounded live fetch and report per-CIK status."""
    args = build_parser().parse_args(argv)
    settings = resolve_runtime_settings()

    try:
        manifest = read_cik_manifest(args.input)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    sample = manifest.ciks[: max(1, args.sample_size)]
    plan = build_plan(
        roster_from_manifest(
            replace(
                manifest,
                ciks=sample,
                names=manifest.names[: len(sample)],
            )
        ),
        chunk_size=(
            settings.default_chunk_size if args.chunk_size is None else args.chunk_size
        ),
        input_name=manifest.input_name,
        input_fingerprint=manifest.input_fingerprint,
        selected_limit=max(1, args.sample_size),
    )

    artifacts = Path(args.artifacts).resolve()
    if not str(artifacts).startswith(str(Path.cwd() / "preview")) and "preview" not in (
        artifacts.parts
    ):
        print(
            "error: --artifacts must point at a preview directory, never a "
            "production snapshot root",
            file=sys.stderr,
        )
        return 2

    run_paths = resolve_run_paths(plan.plan_id, artifacts)
    write_plan(plan, run_paths)

    client = _build_client(run_paths.metadata.artifacts_root)
    workers = resolve_workers(args.workers or None)

    result = run_chunk(
        client,
        plan,
        run_paths,
        0,
        snapshot_id=plan.plan_id,
        workers=workers,
    )
    reclaim()

    import pyarrow.parquet as pq

    table = pq.read_table(result.path, columns=["cik", "status", "error"])
    rows = table.to_pylist()

    failed = [row for row in rows if row["status"] == "failed"]
    for row in rows:
        print(f"  {row['cik']}  {row['status']}  {row['error'] or ''}")

    print(
        f"\nsampled {len(rows)} CIK(s) from {manifest.input_name}; "
        f"checkpoint: {result.path}"
    )
    if failed:
        print(f"error: {len(failed)} sampled CIK(s) failed", file=sys.stderr)
        return 1
    print("smoke test passed (no snapshot published)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
