"""Deterministic, no-network selection of materialized filing targets."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable
from pathlib import Path

from defs.runtime.artifacts import load_manifest
from defs.runtime.paths import resolve_paths
from defs.storage import FinalizedArtifact, StorageError

logger = logging.getLogger("filing_extraction.target_plan")


def _emit(progress: Callable[[dict], None] | None, event: dict) -> None:
    if progress is None:
        return
    try:
        progress(event)
    except Exception:
        logger.exception("target plan progress callback failed")


def plan(
    catalog: str,
    output_root: str | None = None,
    *,
    forms: tuple[str, ...] = (),
    amendment: str = "both",
    limit: int | None = None,
    progress: Callable[[dict], None] | None = None,
) -> dict:
    artifacts_root = resolve_paths().artifacts_root.resolve()
    catalog_path = Path(catalog)
    if output_root is None:
        output_root = str(resolve_paths("filing_extraction").runs_root)
    if catalog_path.is_file():
        candidate_paths = [catalog_path]
    elif catalog_path.is_dir():
        candidate_paths = sorted(catalog_path.glob("*.json"))
    else:
        candidate_paths = sorted(
            (artifacts_root / "manifests" / "filing_extraction").glob("*/final/*.json")
        )
    manifests = []
    for path in candidate_paths:
        try:
            item = load_manifest(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if catalog_path.exists() or str(catalog) in {
            str(item.get("run_id")),
            str(item.get("provenance", {}).get("catalog_id")),
        }:
            manifests.append(item)
    target_manifests = [m for m in manifests if m.get("dataset") == "filing_targets"]
    if not target_manifests:
        raise StorageError("no published filing_targets manifests found for catalog")
    catalog_id = target_manifests[0].get("run_id")
    target_manifests = [m for m in target_manifests if m.get("run_id") == catalog_id]
    selected_forms = set(forms)
    if amendment not in {"both", "original", "amendments"}:
        raise ValueError("amendment must be both, original, or amendments")
    catalog_hash = json.dumps(
        [
            m["artifact_id"]
            for m in sorted(target_manifests, key=lambda x: x["artifact_id"])
        ],
        separators=(",", ":"),
    )
    run_id = hashlib.sha256(catalog_hash.encode()).hexdigest()[:24]
    destination = Path(output_root).resolve() / run_id
    if destination.exists():
        existing = destination / "plan.json"
        if existing.exists():
            return json.loads(existing.read_text(encoding="utf-8"))
        raise StorageError("immutable target plan directory already exists")
    destination.mkdir(parents=True)
    selected: list[str] = []
    selected_entries = []
    for item in sorted(target_manifests, key=lambda m: m["artifact_path"]):
        match = re.search(r"/form=([^/]+)/", item["artifact_path"])
        form = match.group(1) if match else ""
        if selected_forms and form not in selected_forms:
            continue
        if amendment == "original" and form.upper().endswith("_A"):
            continue
        if amendment == "amendments" and not form.upper().endswith("_A"):
            continue
        selected.append(form)
        selected_entries.append((form, item))
    _emit(
        progress,
        {
            "type": "merge_stage",
            "stage": "select_targets",
            "forms": len(selected),
            "total_units": len(selected) + 2,
        },
    )
    counts = {}
    source_artifact_ids = {}
    for form, item in selected_entries:
        source = artifacts_root / item["artifact_path"]
        partition = form
        destination_file = (
            destination / "targets" / f"form={partition}" / "data.parquet"
        )
        destination_file.parent.mkdir(parents=True, exist_ok=True)
        where = ""
        params = []
        if limit is not None:
            if limit < 0:
                raise ValueError("limit must be non-negative")
            where = "LIMIT ?"
            params = [limit]
        with FinalizedArtifact(source) as artifact:
            query = f"SELECT * FROM {artifact.relation} {where}"
            counts[form] = artifact.copy_query(query, destination_file, params)
        source_artifact_ids[form] = item["artifact_id"]
        _emit(
            progress,
            {
                "type": "merge_stage",
                "stage": f"targets:{partition}",
                "rows": counts[form],
            },
        )
    result = {
        "catalog_id": catalog_id,
        "catalog_sha256": hashlib.sha256(catalog_hash.encode()).hexdigest(),
        "forms": list(forms),
        "amendment": amendment,
        "limit": limit,
        "counts": counts,
        "source_artifact_ids": source_artifact_ids,
        "run_id": run_id,
    }
    (destination / "plan.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _emit(
        progress,
        {"type": "merge_stage", "stage": "publish_plan", "rows": sum(counts.values())},
    )
    return result
