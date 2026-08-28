"""Discovery of Phase 02 catalogs and target plans for status reporting.

Status reads only the small JSON manifests that materialize and plan already
write (``catalog_manifest.json`` and ``plan.json``). It never opens or row-scans
the Parquet artifacts, and it never re-fetches source data. Paths returned in
summaries are display-only; consumers must resolve them through the configured
roots, never persist them as absolute paths.
"""

from __future__ import annotations

import json
from pathlib import Path

from defs.runtime.paths import resolve_paths


def _load_json(path: Path) -> dict | None:
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _safe_int(value) -> int:
    return value if isinstance(value, int) else 0


def discover_catalogs(catalogs_root: str | None = None) -> list[dict]:
    """Return summaries for every catalog directory with a manifest.

    A directory is reported only when it contains a parseable
    ``catalog_manifest.json``; malformed JSON is skipped rather than raising.
    """
    if catalogs_root is None:
        catalogs_root = str(resolve_paths("filing_extraction").catalogs_root)
    root = Path(catalogs_root)
    summaries: list[dict] = []
    if not root.exists():
        return summaries
    for catalog_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        manifest = _load_json(catalog_dir / "catalog_manifest.json")
        if manifest is None:
            continue
        form_partitions = manifest.get("form_partitions") or {}
        target_rows = sum(_safe_int(v) for v in form_partitions.values())
        summaries.append(
            {
                "catalog_id": manifest.get("catalog_id", catalog_dir.name),
                "path": str(catalog_dir),
                "source_artifact": manifest.get("source_artifact"),
                "source_artifact_sha256": manifest.get("source_artifact_sha256"),
                "form_count": len(form_partitions),
                "target_rows": target_rows,
            }
        )
    return summaries


def discover_plans(runs_root: str | None = None) -> list[dict]:
    """Return summaries for every target-plan run directory with a ``plan.json``.

    Only the recorded plan metadata is reported; Parquet outputs are never read.
    """
    if runs_root is None:
        runs_root = str(resolve_paths("filing_extraction").runs_root)
    root = Path(runs_root)
    summaries: list[dict] = []
    if not root.exists():
        return summaries
    for run_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        plan = _load_json(run_dir / "plan.json")
        if plan is None:
            continue
        counts = plan.get("counts") or {}
        selected_rows = sum(_safe_int(v) for v in counts.values())
        summaries.append(
            {
                "run_id": plan.get("run_id", run_dir.name),
                "path": str(run_dir),
                "catalog_id": plan.get("catalog_id"),
                "forms": list(plan.get("forms") or []),
                "amendment": plan.get("amendment"),
                "limit": plan.get("limit"),
                "selected_rows": selected_rows,
            }
        )
    return summaries


def status(catalogs_root: str | None = None, runs_root: str | None = None) -> dict:
    """Combined catalog and target-plan discovery for the status command/menu."""
    return {
        "catalogs": discover_catalogs(catalogs_root),
        "plans": discover_plans(runs_root),
    }


__all__ = ["discover_catalogs", "discover_plans", "status"]
