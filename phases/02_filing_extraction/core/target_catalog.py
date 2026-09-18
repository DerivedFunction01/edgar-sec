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
    fp = resolve_filing_paths()
    snap_root = fp.catalog_snapshots_dir
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
    target_dir = snap_manifest_file.parent / "filing_targets"
    for form_dir in sorted(target_dir.glob("form=*")):
        form_key = form_dir.name.split("=", 1)[1]
        data_file = form_dir / "data.parquet"
        if data_file.is_file():
            row_cnt = data.get("form_partitions", {}).get(form_key, 0)
            manifests.append(
                {
                    "artifact_id": f"{cat_id}_{form_key}",
                    "run_id": cat_id,
                    "dataset": "filing_targets",
                    "artifact_path": str(data_file),
                    "row_count": row_cnt,
                    "provenance": {
                        "catalog_id": cat_id,
                        "form_partition_key": form_key,
                    },
                }
            )

    if not manifests:
        raise StorageError(f"no filing targets found in catalog snapshot {cat_id}")

    return cat_id, manifests


__all__ = ["resolve_catalog_manifests"]
