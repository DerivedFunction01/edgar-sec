"""Reusable command-line plumbing for phase entry points."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable


def coalesce(cli_value, config_value, default):
    return (
        cli_value
        if cli_value is not None
        else config_value
        if config_value is not None
        else default
    )


def add_common_options(
    parser: argparse.ArgumentParser, *, include_partition: bool = True
) -> None:
    parser.add_argument(
        "--config", default=None, help="path to persisted project configuration"
    )
    parser.add_argument("--input", default=None, help="input manifest")
    parser.add_argument("--artifacts", default=None, help="run artifacts directory")
    parser.add_argument("--chunk-size", type=int, default=None)
    parser.add_argument("--partition-count", type=int, default=None)
    if include_partition:
        parser.add_argument("--partition-id", type=int, default=None)
    parser.add_argument("--storage-format", choices=("parquet", "jsonl"), default=None)
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--max-retries", type=int, default=None)
    parser.add_argument("--rate-limit", type=float, default=None)
    parser.add_argument("--user-agent", default=None)
    parser.add_argument("--cache-dir", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--run-id", default="local")


def load_config_or_template(
    path: str, *, load: Callable, write: Callable, default: Callable
):
    if os.path.exists(path):
        return load(path), False
    created = write(path, default())
    print(f"Config not found. Created template at {created}")
    print("Edit the config to add SEC User-Agent and review paths, then re-run.")
    raise SystemExit(0)


def print_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


__all__ = ["add_common_options", "coalesce", "load_config_or_template", "print_json"]
