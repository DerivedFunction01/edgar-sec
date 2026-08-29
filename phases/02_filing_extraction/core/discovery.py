"""Discovery of published Phase 02 manifests and target plans."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from defs.runtime.artifacts import load_manifest
from defs.runtime.paths import resolve_paths
from defs.storage import load_json


def _safe_int(value: Any) -> int:
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
        if "target_plans" in path.parts:
            continue
        try:
            manifest = load_manifest(path)
            art_path = Path(manifest["artifact_path"])
            if not art_path.is_absolute():
                art_path = Path(manifests_root).parent / art_path
            if not art_path.is_file():
                # Also check relative to manifests_root or next to manifest
                alt_cand = path.parent / Path(manifest["artifact_path"]).name
                if alt_cand.is_file():
                    art_path = alt_cand
                else:
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


def discover_plans(
    runs_root: str | None = None, manifests_root: str | None = None
) -> list[dict]:
    """Return summaries for published and transient target plans."""
    resolved = resolve_paths("filing_extraction")
    if runs_root is None:
        runs_root = str(resolved.runs_root)
    if manifests_root is None:
        manifests_root = str(resolved.project.manifests_root)

    roots_to_scan = [
        Path(runs_root),
        Path(manifests_root) / "filing_extraction" / "target_plans" / "final",
    ]

    seen_plan_ids = set()
    summaries: list[dict] = []

    for root in roots_to_scan:
        if not root.exists():
            continue
        for plan_file in sorted(root.glob("*/plan.json")):
            plan = load_json(plan_file, default=None)
            if not isinstance(plan, dict):
                continue
            plan_id = str(
                plan.get("plan_id") or plan.get("run_id") or plan_file.parent.name
            )
            if plan_id in seen_plan_ids:
                continue
            seen_plan_ids.add(plan_id)

            counts = plan.get("counts") or {}
            selected_rows = sum(_safe_int(v) for v in counts.values())
            active_targets = plan.get("active_targets_count", selected_rows)
            unique_locators = plan.get("unique_locators_count")

            summaries.append(
                {
                    "run_id": plan_id,
                    "plan_id": plan_id,
                    "path": str(plan_file.parent),
                    "catalog_id": plan.get("catalog_id"),
                    "scope": plan.get("scope", "full"),
                    "policy_corpus": plan.get("policy_corpus"),
                    "policy_fingerprint": plan.get("policy_fingerprint"),
                    "forms": list(plan.get("forms") or []),
                    "amendment": plan.get("amendment"),
                    "limit": plan.get("limit"),
                    "selected_rows": selected_rows,
                    "active_targets_count": active_targets,
                    "unique_locators_count": unique_locators,
                    "reserve_count": plan.get("reserve_count", 0),
                }
            )
    return summaries


def status(manifests_root: str | None = None, runs_root: str | None = None) -> dict:
    """Combined published-catalog and plan discovery."""
    return {
        "catalogs": discover_catalogs(manifests_root),
        "plans": discover_plans(runs_root, manifests_root),
    }


__all__ = ["discover_catalogs", "discover_plans", "status"]
