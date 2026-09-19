"""Production chunk runner and interactive Phase 1 operator shim."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm

from defs.runtime.cli import coalesce
from defs.runtime.progress import make_tqdm_callback

from .core import (
    PROJECT_CONFIG_DEFAULT_PATH,
    ProjectConfig,
    RunOptions,
    default_project_config,
    load_plan,
    load_project_config,
    run_chunk,
    write_project_config,
)
from .operator import interactive_wizard, options_from_args, print_json

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
    parser.add_argument(
        "--source-manifest", default=None, help="immutable source snapshot manifest"
    )
    parser.add_argument(
        "--base-metadata-manifest",
        default=None,
        help="finalized metadata manifest used as augmentation baseline",
    )
    parser.add_argument(
        "--augmentation",
        action="store_true",
        help="run only CIKs missing from a finalized metadata manifest",
    )
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
    parser.add_argument(
        "--threads", type=int, default=None, help="temporary thread-pool override"
    )
    parser.add_argument("--limit", type=int, default=None, help="bounded test run size")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--run-id", default="default")
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="disable the tqdm progress bars (useful for cron/automation logs)",
    )
    return parser


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
            partition_count=coalesce(
                getattr(args, "partition_count", None),
                project_config.partition_count,
                RunOptions.partition_count,
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
