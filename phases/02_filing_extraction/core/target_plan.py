"""Deterministic, no-network selection of materialized filing targets."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path

from defs.storage import FinalizedArtifact, StorageError, file_sha256

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
    output_root: str = ".artifacts/filing_extraction/runs",
    *,
    forms: tuple[str, ...] = (),
    amendment: str = "both",
    limit: int | None = None,
    progress: Callable[[dict], None] | None = None,
) -> dict:
    root = Path(catalog).resolve()
    manifest_path = root / "catalog_manifest.json"
    if not manifest_path.exists():
        raise StorageError("catalog_manifest.json is required")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    selected_forms = set(forms)
    if amendment not in {"both", "original", "amendments"}:
        raise ValueError("amendment must be both, original, or amendments")
    run_id = file_sha256(str(manifest_path))[:24]
    destination = Path(output_root).resolve() / run_id
    if destination.exists():
        existing = destination / "plan.json"
        if existing.exists():
            return json.loads(existing.read_text(encoding="utf-8"))
        raise StorageError("immutable target plan directory already exists")
    destination.mkdir(parents=True)
    selected: list[str] = []
    for form, _count in sorted(manifest.get("form_partitions", {}).items()):
        if selected_forms and form not in selected_forms:
            continue
        if amendment == "original" and form.upper().endswith("/A"):
            continue
        if amendment == "amendments" and not form.upper().endswith("/A"):
            continue
        selected.append(form)
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
    for form in selected:
        partition = manifest["form_partition_mapping"][form]
        source = root / "filing_targets" / f"form={partition}" / "data.parquet"
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
            query = f"SELECT * FROM {artifact.relation} ORDER BY source_cik, accession, document_path {where}"
            counts[form] = artifact.copy_query(query, destination_file, params)
        _emit(
            progress,
            {
                "type": "merge_stage",
                "stage": f"targets:{partition}",
                "rows": counts[form],
            },
        )
    result = {
        "catalog_id": manifest.get("catalog_id"),
        "catalog_sha256": file_sha256(str(manifest_path)),
        "forms": list(forms),
        "amendment": amendment,
        "limit": limit,
        "counts": counts,
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
