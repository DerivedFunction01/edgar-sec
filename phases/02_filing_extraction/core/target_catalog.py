"""Catalog-manifest resolution shared by target-plan operations."""

from __future__ import annotations

from pathlib import Path

from defs.runtime.artifacts import get_current_snapshot_pointer
from defs.storage import StorageError, load_json

from .paths import resolve_filing_paths


def resolve_catalog_manifests(
    catalog: str, artifacts_root: Path, manifests_root: Path
) -> tuple[str, list[dict]]:
    """Resolve catalog target manifests from snapshots."""
    filing_paths = resolve_filing_paths(
        env={"ARTIFACTS_ROOT": str(manifests_root.parent)}
    )
    snap_root = filing_paths.catalog_snapshots_dir
    snap_manifest_file = None

    if not catalog:
        pointer = get_current_snapshot_pointer(
            artifacts_root, phase="filing_extraction", dataset="filing_catalog"
        )
        if pointer and "manifest_path" in pointer:
            cand = artifacts_root / pointer["manifest_path"]
            if cand.is_file():
                snap_manifest_file = cand
    elif (snap_root / catalog / "snapshot.manifest.json").is_file():
        snap_manifest_file = snap_root / catalog / "snapshot.manifest.json"
    elif catalog.endswith("snapshot.manifest.json") and Path(catalog).is_file():
        snap_manifest_file = Path(catalog)
    elif (
        Path(catalog).is_dir() and (Path(catalog) / "snapshot.manifest.json").is_file()
    ):
        snap_manifest_file = Path(catalog) / "snapshot.manifest.json"
    elif (artifacts_root / catalog / "snapshot.manifest.json").is_file():
        snap_manifest_file = artifacts_root / catalog / "snapshot.manifest.json"
    else:
        pointer = get_current_snapshot_pointer(
            artifacts_root, phase="filing_extraction", dataset="filing_catalog"
        )
        if pointer and "manifest_path" in pointer:
            cand = artifacts_root / pointer["manifest_path"]
            if cand.is_file():
                data = load_json(cand, default={})
                if str(data.get("snapshot_id")) == str(catalog) or str(
                    data.get("catalog_id")
                ) == str(catalog):
                    snap_manifest_file = cand
        if not snap_manifest_file and catalog:
            for snap_cand in artifacts_root.rglob("snapshot.manifest.json"):
                if snap_cand.parent.name == catalog:
                    snap_manifest_file = snap_cand
                    break

    if not snap_manifest_file or not snap_manifest_file.is_file():
        raise StorageError(
            f"no published filing_catalog snapshot found for catalog {catalog or '(current)'}"
        )

    data = load_json(snap_manifest_file)
    cat_id = str(
        data.get("snapshot_id")
        or data.get("catalog_id")
        or snap_manifest_file.parent.name
    )
    manifests = []
    parts = data.get("parts", [])
    snap_dir = snap_manifest_file.parent

    if parts:
        for p in parts:
            part_path = snap_dir / p["path"]
            if part_path.is_file():
                manifests.append(
                    {
                        "artifact_id": f"{cat_id}_{part_path.stem}",
                        "run_id": cat_id,
                        "dataset": "filing_targets",
                        "artifact_path": str(part_path),
                        "row_count": p.get("row_count", 0),
                        "provenance": {
                            "catalog_id": cat_id,
                        },
                    }
                )
    else:
        for part_file in sorted((snap_dir / "filing_targets").glob("*.parquet")):
            manifests.append(
                {
                    "artifact_id": f"{cat_id}_{part_file.stem}",
                    "run_id": cat_id,
                    "dataset": "filing_targets",
                    "artifact_path": str(part_file),
                    "row_count": 0,
                    "provenance": {
                        "catalog_id": cat_id,
                    },
                }
            )

    if not manifests:
        raise StorageError(f"no filing targets found in catalog snapshot {cat_id}")

    return cat_id, manifests


__all__ = ["resolve_catalog_manifests"]
