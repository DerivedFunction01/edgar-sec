"""Typed options for the classification surface, shared by CLI/operator."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from edgar_sec.foundation.runtime.paths import resolve_paths

from .paths import ClassificationPaths

__all__ = ["SurfaceOptions", "build_parser", "options_from_args"]


@dataclass(frozen=True, slots=True)
class SurfaceOptions:
    """Roots the CLI and operator surface reads and writes."""

    artifacts_root: Path | None = None
    plans_root: Path | None = None
    store_root: Path | None = None

    def resolved_artifacts_root(self) -> Path:
        if self.artifacts_root is not None:
            return Path(self.artifacts_root)
        return resolve_paths().artifacts_root

    def classification_paths(self) -> ClassificationPaths:
        """The core layout this surface plans and reads through.

        A plans-root override is read as the canonical plans root (its
        grandparent is the artifacts root); otherwise that root governs.
        """
        if self.plans_root is not None:
            artifacts = Path(self.plans_root).parent.parent
            return ClassificationPaths(artifacts_root=artifacts)
        return ClassificationPaths(artifacts_root=self.resolved_artifacts_root())

    def resolved_plans_root(self) -> Path:
        return self.classification_paths().plans_root

    def resolved_store_root(self) -> Path:
        if self.store_root is not None:
            return Path(self.store_root)
        return self.resolved_artifacts_root() / "table_classification" / "store"


def _root_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--artifacts", default="", help="artifacts root override")
    parser.add_argument("--plans-root", default="", help="plans root override")
    parser.add_argument("--store-root", default="", help="store root override")
    parser.add_argument("--json", action="store_true", help="emit JSON")


def build_parser() -> argparse.ArgumentParser:
    """Argument parser for the table_classification command surface."""
    parser = argparse.ArgumentParser(prog="table_classification")
    sub = parser.add_subparsers(dest="command", required=True)

    translate = sub.add_parser(
        "translate", help="registry exhibit links as generic planning triples"
    )
    translate.add_argument("--family", action="append", default=[])
    translate.add_argument("--stratum", default="")
    translate.add_argument("--json", action="store_true")

    plan = sub.add_parser("plan", help="plan a classification run against the registry")
    plan.add_argument("--accession", action="append", default=[], required=True)
    plan.add_argument("--snapshot-id", default="")
    plan.add_argument("--stratum", default="")
    plan.add_argument("--family", action="append", default=[])
    plan.add_argument("--normalize-version", default="")
    plan.add_argument("--renderer-version", default="")
    plan.add_argument("--form", default="")
    plan.add_argument(
        "--provenance-route",
        default="render_to_txt",
        choices=["raw", "render_to_txt", "render_to_xml"],
    )
    plan.add_argument("--output", default="", help="plans root override for this plan")
    plan.add_argument("--json", action="store_true")

    run = sub.add_parser("run", help="run a planned classification (pipeline core)")
    run.add_argument("--plan-id", required=True)
    _root_args(run)

    inspect = sub.add_parser("inspect", help="validate and inspect a planned run")
    inspect.add_argument("--plan-id", required=True)
    _root_args(inspect)

    status = sub.add_parser("status", help="list plans and the published store state")
    _root_args(status)

    review = sub.add_parser("review", help="review-run surface (fixture/review lane)")
    review.add_argument("--plan-id", default="")
    review.add_argument("rest", nargs=argparse.REMAINDER)
    _root_args(review)

    fixture = sub.add_parser("fixture", help="fixture surface (fixture/review lane)")
    fixture.add_argument("--fixture-id", default="")
    fixture.add_argument("rest", nargs=argparse.REMAINDER)
    _root_args(fixture)
    return parser


def options_from_args(args: argparse.Namespace) -> SurfaceOptions:
    """SurfaceOptions from parsed CLI arguments."""
    plans = getattr(args, "output", "") or getattr(args, "plans_root", "")
    return SurfaceOptions(
        artifacts_root=Path(args.artifacts) if getattr(args, "artifacts", "") else None,
        plans_root=Path(plans) if plans else None,
        store_root=Path(args.store_root) if getattr(args, "store_root", "") else None,
    )
