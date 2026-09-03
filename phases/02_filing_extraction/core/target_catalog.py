"""Catalog-manifest resolution shared by target-plan operations."""

from __future__ import annotations

import json
from pathlib import Path

from defs.runtime.artifacts import load_manifest
from defs.storage import StorageError


def resolve_catalog_manifests(
    catalog: str, artifacts_root: Path, manifests_root: Path
) -> tuple[str, list[dict]]:
    catalog_path = Path(catalog) if catalog else None
    if catalog_path and catalog_path.is_file():
        candidate_paths = [catalog_path]
    elif catalog_path and catalog_path.is_dir():
        candidate_paths = sorted(catalog_path.glob("*.json"))
    else:
        candidate_paths = sorted((manifests_root / "filing_extraction").rglob("*.json"))
    distinct_manifests = {}
    for path in candidate_paths:
        try:
            item = load_manifest(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        art_id = item.get("artifact_id")
        if not art_id or art_id in distinct_manifests:
            continue
        if (
            not catalog
            or (catalog_path and catalog_path.exists())
            or str(catalog)
            in {
                str(item.get("run_id")),
                str(item.get("provenance", {}).get("catalog_id")),
            }
        ):
            distinct_manifests[art_id] = item
    manifests = list(distinct_manifests.values())
    target_manifests = [m for m in manifests if m.get("dataset") == "filing_targets"]
    if not target_manifests:
        raise StorageError("no published filing_targets manifests found for catalog")
    catalog_id = str(target_manifests[0].get("run_id") or "")
    return catalog_id, [m for m in manifests if str(m.get("run_id")) == catalog_id]


__all__ = ["resolve_catalog_manifests"]
