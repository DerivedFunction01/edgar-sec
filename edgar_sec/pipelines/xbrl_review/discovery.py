"""Manifest-only discovery for cohorts and review runs in XBRL review."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from edgar_sec.engine.xbrl.discovery.cohort import (
    canonical_seed_cohort_path,
    canonical_vintage_cohort_path,
)
from edgar_sec.pipelines.xbrl_review.paths import (
    default_sp100_cohort_path,
    xbrl_paths,
)


def _describe_cohort(cohort_id: str, name: str, path: Path) -> dict[str, Any]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    fys = [int(row["fy"]) for row in rows]
    return {
        "cohort_id": cohort_id,
        "label": f"{name} Cohort ({len(rows)} Filings, FY{min(fys)}–FY{max(fys)})",
        "path": path,
    }


def discover_cohorts(
    artifacts_root: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Discover available cohorts for XBRL review and benchmark validation."""
    cohorts: list[dict[str, Any]] = []

    seed_p = canonical_seed_cohort_path()
    if seed_p.is_file():
        cohorts.append(_describe_cohort("seed", "Seed", seed_p))

    vintage_p = canonical_vintage_cohort_path()
    if vintage_p.is_file():
        cohorts.append(_describe_cohort("vintage", "Vintage", vintage_p))

    sp100_p = default_sp100_cohort_path(artifacts_root)
    if sp100_p.is_file():
        cohorts.append(_describe_cohort("sp100", "S&P 100 Robustness", sp100_p))

    return cohorts


def discover_review_runs(
    artifacts_root: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Discover historical review runs and manifests without heavy file scans."""
    paths = xbrl_paths(artifacts_root=artifacts_root)
    runs_dir = paths.review_runs_root
    if not runs_dir.is_dir():
        return []

    runs: list[dict[str, Any]] = []
    for entry in sorted(runs_dir.iterdir(), reverse=True):
        if entry.is_dir() and entry.name.startswith("run-"):
            manifest_file = entry / "manifest.jsonl"
            details: dict[str, Any] = {}
            if manifest_file.is_file():
                try:
                    details = json.loads(manifest_file.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    pass
            runs.append(
                {
                    "run_id": entry.name,
                    "path": entry,
                    "created_at": details.get("created_at", ""),
                    "total_filings": details.get("total_filings", 0),
                    "total_solved_nodes": details.get("total_solved_nodes", 0),
                    "total_hypotheses": details.get("total_hypotheses", 0),
                }
            )
    return runs


__all__ = [
    "default_sp100_cohort_path",
    "discover_cohorts",
    "discover_review_runs",
]
