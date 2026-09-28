"""Manifest-only discovery of published catalogs and target plans.

Every function here reads JSON manifests and directory listings only. It never
opens a Parquet payload, never materializes a catalog, and never contacts the
network, so ``status`` stays cheap enough to call from a menu loop or a
preflight check.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from edgar_sec.pipelines.filing_catalog.paths import (
    CURRENT_ALIAS,
    PLAN_FILE_NAME,
    SNAPSHOT_MANIFEST_NAME,
    FilingCatalogPaths,
    resolve_filing_catalog_paths,
    safe_identifier,
)


def _read_json(path: Path) -> dict[str, Any] | None:
    """Return parsed JSON, or None when absent or unreadable.

    A truncated manifest is reported as absent rather than raising, so a single
    damaged directory cannot make discovery fail for every other entry.
    """
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def current_catalog_id(paths: FilingCatalogPaths) -> str | None:
    """Return the catalog id named by the current pointer, if any."""
    pointer = _read_json(paths.current_pointer)
    if pointer is None:
        return None
    catalog_id = pointer.get("catalog_id") or pointer.get("snapshot_id")
    return str(catalog_id) if catalog_id else None


def resolve_catalog_manifest(
    paths: FilingCatalogPaths, catalog: str
) -> dict[str, Any] | None:
    """Resolve a catalog id, or the literal ``current``, to its manifest."""
    if catalog == CURRENT_ALIAS:
        catalog_id = current_catalog_id(paths)
        if catalog_id is None:
            return None
    else:
        catalog_id = safe_identifier(catalog)
    return _read_json(paths.snapshot_manifest(catalog_id))


def discover_catalogs(
    paths: FilingCatalogPaths | None = None,
) -> list[dict[str, Any]]:
    """List every published catalog snapshot, newest id last.

    Results are sorted by catalog id for a stable presentation order; the id is
    content-derived, so lexical order is meaningful and reproducible.
    """
    resolved = paths or resolve_filing_catalog_paths()
    found: list[dict[str, Any]] = []
    if not resolved.snapshots_root.is_dir():
        return found
    for entry in sorted(resolved.snapshots_root.iterdir()):
        if not entry.is_dir() or entry.name == CURRENT_ALIAS:
            continue
        manifest = _read_json(entry / SNAPSHOT_MANIFEST_NAME)
        if manifest is None:
            continue
        found.append(
            {
                "catalog_id": entry.name,
                "profile_row_count": manifest.get("profile_row_count"),
                "target_row_count": manifest.get("target_row_count"),
                "schema_version": manifest.get("schema_version"),
                "part_count": len(manifest.get("parts") or []),
                "form_counts": manifest.get("form_counts") or {},
                "source_artifact": manifest.get("source_artifact"),
            }
        )
    return found


def discover_plans(paths: FilingCatalogPaths | None = None) -> list[dict[str, Any]]:
    """List every published target-plan bundle."""
    resolved = paths or resolve_filing_catalog_paths()
    found: list[dict[str, Any]] = []
    if not resolved.plans_root.is_dir():
        return found
    for entry in sorted(resolved.plans_root.iterdir()):
        if not entry.is_dir():
            continue
        plan = _read_json(entry / PLAN_FILE_NAME)
        if plan is None:
            continue
        found.append(
            {
                "plan_id": entry.name,
                "catalog_id": plan.get("catalog_id"),
                "scope": plan.get("scope"),
                "forms": plan.get("forms") or [],
                "amendment": plan.get("amendment"),
                "document_suffixes": plan.get("document_suffixes") or [],
                "limit": plan.get("limit"),
                "selected_rows": plan.get("selected_rows"),
                "unique_locators_count": plan.get("unique_locators_count"),
                "counts": plan.get("counts") or {},
            }
        )
    return found


def status(paths: FilingCatalogPaths | None = None) -> dict[str, Any]:
    """Summarize published state from manifests alone."""
    resolved = paths or resolve_filing_catalog_paths()
    catalogs = discover_catalogs(resolved)
    plans = discover_plans(resolved)
    current = current_catalog_id(resolved)
    return {
        "artifacts_root": str(resolved.artifacts_root),
        "current_catalog_id": current,
        "catalog_count": len(catalogs),
        "plan_count": len(plans),
        "catalogs": catalogs,
        "plans": plans,
        "total_planned_rows": sum(
            int(plan.get("selected_rows") or 0) for plan in plans
        ),
    }


__all__ = [
    "CURRENT_ALIAS",
    "current_catalog_id",
    "discover_catalogs",
    "discover_plans",
    "resolve_catalog_manifest",
    "status",
]
