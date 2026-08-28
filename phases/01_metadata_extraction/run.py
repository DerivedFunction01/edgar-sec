"""Production chunk runner with an optional interactive wizard.

Non-interactive (single chunk, suitable for automation and multi-machine
fan-out):

    python -m phases.01_metadata_extraction.run \
        --input uploads/cik-sec.csv \
        --artifacts .artifacts/metadata/runs/<run-id> \
        --chunk-size 1000 --chunk-id 12 --workers 4

Interactive (no --chunk-id): a wizard that uses persisted configuration and
reuses the shared partition-oriented operator menu:

   1. Preview
   2. Run partition
   3. Show partition commands (for dividing work across machines)
   4. Show status
   5. Merge a partition from its chunks
   6. Merge all partition artifacts into the final dataset
   0. Exit

Two-stage merge is the supported path for partitioned runs: each machine
publishes its partition artifact, those artifacts are copied into the
coordinator run's partition layout, then option 6 combines them without
touching the source chunk directories.

All execution still goes through the shared core (build_plan, run_chunk,
get_status); this shim never duplicates fetching, normalization, or
checkpoint logic. Exits nonzero on validation or network failures.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm

from defs.runtime.interactive import InteractivePhase, run_interactive
from defs.runtime.progress import make_merge_progress_callback, make_tqdm_callback

from .core import (
    PROJECT_CONFIG_DEFAULT_PATH,
    ProjectConfig,
    RunOptions,
    build_plan,
    default_project_config,
    default_user_agent,
    get_status,
    load_plan,
    load_project_config,
    merge,
    merge_one_partition,
    preview_sample,
    run_chunk,
    run_partition,
    write_project_config,
)
from .core.merge import MergeError

log = logging.getLogger("metadata.run")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="phases.01_metadata_extraction.run",
        description="Run one chunk non-interactively, or launch the interactive wizard when --chunk-id is omitted.",
    )
    parser.add_argument(
        "--config",
        default=PROJECT_CONFIG_DEFAULT_PATH,
        help="path to the persisted project configuration (default: .artifacts/metadata/config.json)",
    )
    parser.add_argument(
        "--configure",
        action="store_true",
        help="create or update the config file from supplied CLI settings and exit",
    )
    parser.add_argument("--input", default=None, help="CIK/name CSV manifest")
    parser.add_argument("--artifacts", default=None, help="run artifacts directory")
    parser.add_argument("--chunk-size", type=int, default=None, help="CIKs per chunk")
    parser.add_argument(
        "--partition-count",
        type=int,
        default=None,
        help="number of deterministic work partitions",
    )
    parser.add_argument(
        "--partition-id", type=int, default=None, help="operational partition to run"
    )
    parser.add_argument(
        "--storage-format",
        choices=("parquet", "jsonl"),
        default=None,
        help="checkpoint format (Parquet by default; JSONL is useful for inspection)",
    )
    parser.add_argument(
        "--chunk-id",
        type=int,
        default=None,
        help="omit to start the interactive wizard",
    )
    parser.add_argument("--workers", type=int, default=None, help="concurrent workers")
    parser.add_argument(
        "--timeout", type=float, default=None, help="request timeout in seconds"
    )
    parser.add_argument(
        "--max-retries", type=int, default=None, help="per-request retry budget"
    )
    parser.add_argument(
        "--rate-limit",
        type=float,
        default=None,
        help="target requests/second per process",
    )
    parser.add_argument(
        "--user-agent",
        default=None,
        help="SEC identity: 'AppName/1.0 contact@example.com'",
    )
    parser.add_argument(
        "--cache-dir", default=None, help="optional raw-response cache directory"
    )
    parser.add_argument(
        "--max-failure-attempts",
        type=int,
        default=None,
        help="independent failed runs after which a URL is skipped without retrying",
    )
    parser.add_argument("--limit", type=int, default=None, help="bounded test run size")
    parser.add_argument(
        "--ignore-failure-history",
        action="store_true",
        help="attempt every URL regardless of recorded failures",
    )
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--run-id", default="local")
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="disable the tqdm progress bars (useful for cron/automation logs)",
    )
    return parser


from defs.runtime.cli import coalesce


def options_from_args(args, project_config) -> RunOptions:
    return RunOptions(
        input_path=coalesce(
            args.input, project_config.input_path, RunOptions.input_path
        ),
        artifacts_dir=coalesce(
            args.artifacts, project_config.artifacts_dir, RunOptions.artifacts_dir
        ),
        chunk_size=coalesce(
            args.chunk_size, project_config.chunk_size, RunOptions.chunk_size
        ),
        partition_count=coalesce(
            getattr(args, "partition_count", None),
            project_config.partition_count,
            RunOptions.partition_count,
        ),
        partition_id=getattr(args, "partition_id", None),
        storage_format=coalesce(
            args.storage_format,
            project_config.storage_format,
            RunOptions.storage_format,
        ),
        chunk_id=args.chunk_id,
        workers=coalesce(args.workers, project_config.workers, RunOptions.workers),
        timeout_s=coalesce(
            args.timeout, project_config.timeout_s, RunOptions.timeout_s
        ),
        max_retries=coalesce(
            args.max_retries, project_config.max_retries, RunOptions.max_retries
        ),
        rate_limit_rps=coalesce(
            args.rate_limit, project_config.rate_limit_rps, RunOptions.rate_limit_rps
        ),
        user_agent=(
            args.user_agent
            if getattr(args, "user_agent", None) is not None
            else (project_config.user_agent or default_user_agent())
        ),
        cache_dir=coalesce(args.cache_dir, project_config.cache_dir, ""),
        max_failure_attempts=coalesce(
            args.max_failure_attempts,
            project_config.max_failure_attempts,
            RunOptions.max_failure_attempts,
        ),
        ignore_failure_history=getattr(args, "ignore_failure_history", False),
        limit=coalesce(args.limit, project_config.limit, RunOptions.limit),
        log_level=args.log_level,
        run_id=args.run_id,
    )


def print_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


# ---------------------------------------------------------------------------
# Interactive wizard
# ---------------------------------------------------------------------------


def partition_command(options: RunOptions, partition_id: int) -> str:
    agent = options.user_agent or "$SEC_USER_AGENT"
    storage = (
        f" --storage-format {options.storage_format}"
        if options.storage_format != "parquet"
        else ""
    )
    return (
        f".venv/bin/python -m phases.01_metadata_extraction.cli run"
        f" --config {PROJECT_CONFIG_DEFAULT_PATH} --partition-id {partition_id}"
        f" --input '{options.input_path}' --artifacts '{options.artifacts_dir}'"
        f" --workers {options.workers} --rate-limit {options.rate_limit_rps}"
        f" --user-agent '{agent}'{storage}"
    )


def ensure_plan(options: RunOptions) -> dict:
    try:
        plan = load_plan(options)
        print(
            f"\nLoaded existing plan: {len(plan['chunks'])} chunks, {plan['row_count']} CIKs"
        )
        return plan
    except (FileNotFoundError, ValueError):
        answer = input(
            f"No valid plan.json in {options.artifacts_dir}. Create one now? (y/N) "
        ).strip()
        if answer.lower() not in ("y", "yes"):
            raise SystemExit("aborted: run `plan` first or answer yes to create it")
        plan = build_plan(options)
        print(f"Plan created: {len(plan['chunks'])} chunks, {plan['row_count']} CIKs")
        return plan


def _chunk_row_counts(options: RunOptions) -> dict[int, int]:
    """Map chunk id -> row count from plan.json; empty when no plan exists."""
    try:
        plan = load_plan(options)
    except (FileNotFoundError, ValueError):
        return {}
    return {
        chunk["chunk_id"]: chunk["end_row"] - chunk["start_row"] + 1
        for chunk in plan.get("chunks", [])
    }


def _run_partition_with_progress(
    options: RunOptions, partition_id: int, *, show_progress: bool = True
) -> dict:
    """Run one partition with a single CIK-level progress bar."""
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
    total = sum(
        chunk["end_row"] - chunk["start_row"] + 1
        for chunk in partition.get("chunks", [])
    )
    bar = tqdm(
        total=total,
        unit="cik",
        desc=f"partition {partition_id}",
        disable=not show_progress,
    )
    try:
        with logging_redirect_tqdm():
            return run_partition(
                options, partition_id, progress=make_tqdm_callback(bar)
            )
    finally:
        bar.close()


def _translate_merge_error(func):
    def wrapper(*call_args, **call_kwargs):
        try:
            return func(*call_args, **call_kwargs)
        except MergeError as exc:
            raise ValueError(str(exc)) from exc

    return wrapper


def _merge_partition_with_progress(
    options: RunOptions, partition_id: int, *, show_progress: bool = True
) -> dict:
    """Merge one partition with a stage-level progress bar (validate, publish)."""
    bar = tqdm(
        total=3,
        unit="stage",
        desc=f"merge partition {partition_id}",
        disable=not show_progress,
    )
    try:
        with logging_redirect_tqdm():
            return merge_one_partition(
                options,
                partition_id,
                progress=make_merge_progress_callback(bar),
            ).to_dict()
    finally:
        bar.close()


def _merge_final_with_progress(
    options: RunOptions, *, show_progress: bool = True
) -> dict:
    """Combine partition artifacts with a partition-level progress bar."""
    plan = load_plan(options)
    bar = tqdm(
        total=len(plan.get("partitions", [])) + 2,
        unit="step",
        desc="final merge",
        disable=not show_progress,
    )
    try:
        with logging_redirect_tqdm():
            return merge(
                options,
                os.path.join(
                    options.artifacts_dir,
                    "merge",
                    "submission_metadata.parquet",
                ),
                progress=make_merge_progress_callback(bar),
            ).to_dict()
    finally:
        bar.close()


def interactive_wizard(args, project_config) -> int:
    """Phase 1 adapter for the shared partition-oriented operator UI."""
    options = options_from_args(args, project_config)
    try:
        options.validate()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return run_interactive(
        InteractivePhase(
            ensure_plan=lambda: ensure_plan(options),
            preview=lambda: preview_sample(options),
            status=lambda: get_status(options),
            run_partition=lambda partition_id: _run_partition_with_progress(
                options, partition_id, show_progress=not args.no_progress
            ),
            partition_command=lambda partition_id: partition_command(
                options, partition_id
            ),
            merge_partition=_translate_merge_error(
                lambda partition_id: _merge_partition_with_progress(
                    options, partition_id, show_progress=not args.no_progress
                )
            ),
            merge_final=_translate_merge_error(
                lambda: _merge_final_with_progress(
                    options, show_progress=not args.no_progress
                )
            ),
        )
    )


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(levelname)s %(message)s",
    )

    if args.configure:
        config_path = args.config
        if os.path.exists(config_path):
            try:
                project_config = load_project_config(config_path)
            except (FileNotFoundError, ValueError) as exc:
                print(f"error loading existing config: {exc}", file=sys.stderr)
                return 2
        else:
            project_config = default_project_config()

        updated = ProjectConfig(
            input_path=coalesce(
                args.input, project_config.input_path, RunOptions.input_path
            ),
            artifacts_dir=coalesce(
                args.artifacts, project_config.artifacts_dir, RunOptions.artifacts_dir
            ),
            chunk_size=coalesce(
                args.chunk_size, project_config.chunk_size, RunOptions.chunk_size
            ),
            workers=coalesce(args.workers, project_config.workers, RunOptions.workers),
            timeout_s=coalesce(
                args.timeout, project_config.timeout_s, RunOptions.timeout_s
            ),
            max_retries=coalesce(
                args.max_retries, project_config.max_retries, RunOptions.max_retries
            ),
            rate_limit_rps=coalesce(
                args.rate_limit,
                project_config.rate_limit_rps,
                RunOptions.rate_limit_rps,
            ),
            user_agent=args.user_agent
            or project_config.user_agent
            or default_user_agent(),
            cache_dir=coalesce(args.cache_dir, project_config.cache_dir, ""),
            max_failure_attempts=coalesce(
                args.max_failure_attempts,
                project_config.max_failure_attempts,
                RunOptions.max_failure_attempts,
            ),
            limit=coalesce(args.limit, project_config.limit, RunOptions.limit),
            storage_format=coalesce(
                args.storage_format,
                project_config.storage_format,
                RunOptions.storage_format,
            ),
        )
        try:
            updated.validate()
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        path = write_project_config(config_path, updated)
        print(f"Config written to {path}")
        return 0

    config_path = args.config
    if not os.path.exists(config_path):
        default_cfg = default_project_config()
        path = write_project_config(config_path, default_cfg)
        print(f"Config not found. Created template at {path}")
        print("Edit the config to add SEC User-Agent and review paths, then re-run.")
        return 0

    try:
        project_config = load_project_config(config_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error loading config: {exc}", file=sys.stderr)
        return 2

    if args.chunk_id is None:
        try:
            return interactive_wizard(args, project_config)
        except KeyboardInterrupt:
            print("\ninterrupted")
            return 130

    options = options_from_args(args, project_config)
    bar = tqdm(
        total=_chunk_row_counts(options).get(options.chunk_id),
        unit="cik",
        desc=f"chunk {options.chunk_id}",
        disable=args.no_progress,
    )
    try:
        with logging_redirect_tqdm():
            summary = run_chunk(options, progress=make_tqdm_callback(bar))
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 — network or unexpected failure: nonzero exit
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    finally:
        bar.close()
    print_json(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
