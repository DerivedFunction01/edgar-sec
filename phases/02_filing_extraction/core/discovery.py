"""Discovery of published Phase 02 catalog snapshots and target plans."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from defs.runtime.paths import resolve_paths
from defs.storage import load_json

from .paths import resolve_filing_paths
from .selection_policy import discover_policies as _discover_policies


def _safe_int(value: Any) -> int:
    return value if isinstance(value, int) else 0


def discover_catalogs(manifests_root: str | None = None) -> list[dict]:
    """Discover validated Phase 02 catalog snapshots."""
    fp = resolve_filing_paths()
    if manifests_root is None:
        snap_root = fp.catalog_snapshots_dir
        if not snap_root.exists():
            return []
        snap_manifest_files = sorted(snap_root.glob("*/snapshot.manifest.json"))
    else:
        m_path = Path(manifests_root).resolve()
        if not m_path.exists():
            return []
        snap_manifest_files = sorted(m_path.rglob("snapshot.manifest.json"))

    summaries: list[dict] = []
    seen_catalogs: set[str] = set()

    for snap_manifest in snap_manifest_files:
        try:
            data = load_json(snap_manifest)
            if not isinstance(data, dict):
                continue
            # The manifests tree also holds upstream Phase 1 metadata
            # snapshot manifests; only filing-catalog snapshots are catalogs.
            if data.get("manifest_kind") != "filing_catalog_snapshot":
                continue
            cat_id = str(
                data.get("snapshot_id")
                or data.get("catalog_id")
                or snap_manifest.parent.name
            )
            if cat_id in seen_catalogs:
                continue
            seen_catalogs.add(cat_id)
            forms = sorted(data.get("form_counts", {}).keys())
            summaries.append(
                {
                    "catalog_id": cat_id,
                    "snapshot_id": cat_id,
                    "path": str(snap_manifest.parent),
                    "source_artifact_sha256": data.get("source_artifact_sha256"),
                    "form_count": data.get("form_count", len(forms)),
                    "forms": forms,
                    "target_rows": _safe_int(data.get("target_rows")),
                    "artifact_ids": [cat_id],
                }
            )
        except (OSError, ValueError):
            continue

    return summaries


def discover_plans(
    runs_root: str | None = None, manifests_root: str | None = None
) -> list[dict]:
    """Return summaries for published and transient target plans."""
    if manifests_root is None:
        filing_paths = resolve_filing_paths()
    else:
        filing_paths = resolve_filing_paths(
            env={"ARTIFACTS_ROOT": str(Path(manifests_root).parent)}
        )
    resolved = resolve_paths("filing_extraction")
    if runs_root is None:
        runs_root = str(resolved.runs_root)

    roots_to_scan = [
        Path(runs_root),
        # Immutable published collection of target-plan bundles.
        filing_paths.target_plans_root,
    ]

    seen_plan_ids = set()
    summaries: list[dict] = []

    for root in roots_to_scan:
        if not root.exists():
            continue
        for plan_file in sorted(root.glob("*/plan.json")):
            # Skip transient staging bundles during atomic publication.
            if plan_file.parent.name.startswith("."):
                continue
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
                    "scope": plan.get("scope", "deterministic"),
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


def discover_policies() -> list[dict]:
    """Summarize valid selection policy JSON files in the Phase 2 artifact tree."""
    try:
        return _discover_policies()
    except (OSError, ValueError):
        return []


def status(manifests_root: str | None = None, runs_root: str | None = None) -> dict:
    """Combined published-catalog and plan discovery."""
    return {
        "catalogs": discover_catalogs(manifests_root),
        "plans": discover_plans(runs_root, manifests_root),
    }


__all__ = [
    "discover_catalogs",
    "discover_plans",
    "discover_policies",
    "status",
]
