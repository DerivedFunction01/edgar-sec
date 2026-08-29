"""Discovery of published Phase 02 manifests and transient target plans."""

from __future__ import annotations

import json
import re
from pathlib import Path

from defs.runtime.artifacts import load_manifest
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


def discover_catalogs(manifests_root: str | None = None) -> list[dict]:
    """Group validated Phase 02 final receipts by materialization ID."""
    if manifests_root is None:
        manifests_root = str(resolve_paths("filing_extraction").project.manifests_root)
    root = Path(manifests_root) / "filing_extraction"
    groups: dict[str, list[dict]] = {}
    if not root.exists():
        return []
    for path in sorted(root.glob("*/final/*.json")):
        try:
            manifest = load_manifest(path)
            artifact = Path(manifests_root).parent / manifest["artifact_path"]
            if not artifact.is_file():
                continue
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        catalog_id = str(manifest.get("run_id") or "")
        if not catalog_id:
            continue
        groups.setdefault(catalog_id, []).append(manifest)

    summaries = []
    for catalog_id, manifests in sorted(groups.items()):
        targets = [m for m in manifests if m.get("dataset") == "filing_targets"]
        forms = sorted(
            {
                match.group(1)
                for item in targets
                if (match := re.search(r"/form=([^/]+)/", item["artifact_path"]))
            }
        )
        summaries.append(
            {
                "catalog_id": catalog_id,
                "path": str(root),
                "source_artifact_sha256": next(
                    (
                        m.get("provenance", {}).get("source_artifact_sha256")
                        for m in manifests
                    ),
                    None,
                ),
                "form_count": len(forms),
                "forms": forms,
                "target_rows": sum(_safe_int(m.get("row_count")) for m in targets),
                "artifact_ids": [m["artifact_id"] for m in manifests],
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


def status(manifests_root: str | None = None, runs_root: str | None = None) -> dict:
    """Combined published-catalog and transient-plan discovery."""
    return {
        "catalogs": discover_catalogs(manifests_root),
        "plans": discover_plans(runs_root),
    }


__all__ = ["discover_catalogs", "discover_plans", "status"]
