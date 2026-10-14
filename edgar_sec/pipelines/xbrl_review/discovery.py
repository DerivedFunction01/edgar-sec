"""Manifest-only discovery for cohorts and review runs in XBRL review pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from edgar_sec.pipelines.xbrl_review.paths import resolve_xbrl_review_paths


def discover_cohorts(
    artifacts_root: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Discover available cohorts for XBRL review and benchmark validation."""
    paths = resolve_xbrl_review_paths(artifacts_root=artifacts_root)
    cohorts: list[dict[str, Any]] = []

    seed_p = paths.default_seed_cohort_path
    if seed_p.is_file():
        cohorts.append(
            {
                "cohort_id": "seed",
                "label": "Seed Cohort (15 Filers, Multi-Sector)",
                "path": seed_p,
            }
        )

    sp100_p = paths.default_sp100_cohort_path
    if sp100_p.is_file():
        cohorts.append(
            {
                "cohort_id": "sp100",
                "label": "S&P 100 Robustness Cohort (100 Filers, 11 GICS Sectors)",
                "path": sp100_p,
            }
        )

    if paths.cohorts_dir.is_dir():
        for cp in sorted(paths.cohorts_dir.glob("*.json")):
            cohorts.append(
                {
                    "cohort_id": cp.stem,
                    "label": f"Custom Cohort ({cp.name})",
                    "path": cp,
                }
            )
    return cohorts


def discover_review_runs(
    artifacts_root: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Discover historical review runs and manifests without heavy file scans."""
    paths = resolve_xbrl_review_paths(artifacts_root=artifacts_root)
    runs_dir = paths.review_runs_dir
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
