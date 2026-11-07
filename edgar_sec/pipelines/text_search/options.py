"""Typed options for the text index build, shared by CLI and operator."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from edgar_sec.foundation.runtime.paths import resolve_paths
from edgar_sec.infra.storage.text_index import default_index_root

__all__ = ["BuildOptions", "build_parser", "options_from_args"]


@dataclass(frozen=True, slots=True)
class BuildOptions:
    """Everything that defines one index build."""

    artifacts_root: Path | None = None
    index_root: Path | None = None
    cache_db: Path | None = None

    def resolved_index_root(self) -> Path:
        if self.index_root is not None:
            return Path(self.index_root)
        return default_index_root(self.artifacts_root)

    def resolved_artifacts_root(self) -> Path:
        if self.artifacts_root is not None:
            return Path(self.artifacts_root)
        return resolve_paths().artifacts_root

    def resolved_cache_db(self) -> Path:
        if self.cache_db is not None:
            return Path(self.cache_db)
        return self.resolved_artifacts_root() / "cache" / "documents.sqlite"


def build_parser() -> argparse.ArgumentParser:
    """Argument parser for the text_search command surface."""
    parser = argparse.ArgumentParser(prog="text_search")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="build or incrementally extend the index")
    build.add_argument("--artifacts", default="", help="artifacts root override")
    build.add_argument("--index-root", default="", help="index root override")
    build.add_argument("--cache-db", default="", help="DocumentCache sqlite override")
    status = sub.add_parser("status", help="report the stored index's corpus stats")
    status.add_argument("--artifacts", default="", help="artifacts root override")
    status.add_argument("--index-root", default="", help="index root override")
    return parser


def options_from_args(args: argparse.Namespace) -> BuildOptions:
    """BuildOptions from parsed CLI arguments."""
    return BuildOptions(
        artifacts_root=Path(args.artifacts) if getattr(args, "artifacts", "") else None,
        index_root=Path(args.index_root) if getattr(args, "index_root", "") else None,
        cache_db=Path(args.cache_db) if getattr(args, "cache_db", "") else None,
    )
