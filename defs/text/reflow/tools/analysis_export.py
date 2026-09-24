"""Validate human labels and publish immutable labeled Parquet shards."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from defs.runtime.paths import resolve_paths
from defs.storage import (
    atomic_write_json,
    atomic_write_text,
    file_sha256,
    pa,
    pq,
    write_table_atomic,
)

from .analysis_features import (
    BLOCK_SCHEMA,
    LABELS,
    SCHEMA_VERSION,
    TOKEN_SCHEMA,
    jsonl_records,
    safe_id,
)


def _load_annotations(path: Path) -> dict[str, dict[str, Any]]:
    annotations: dict[str, dict[str, Any]] = {}
    for row in jsonl_records(path):
        block_id = str(row.get("block_id", ""))
        label = str(row.get("label", ""))
        rationale = str(row.get("rationale", "")).strip()
        if not block_id or block_id in annotations:
            raise ValueError("annotation file has a missing or duplicate block_id")
        if label not in LABELS:
            raise ValueError(f"invalid label {label!r} for block {block_id}")
        if not rationale:
            raise ValueError(f"annotation rationale is required for block {block_id}")
        annotations[block_id] = row
    return annotations


def _write_labeled_shard(
    output_root: Path,
    stem: str,
    schema,
    rows: list[dict[str, Any]],
    index: int,
) -> dict[str, Any]:
    directory = output_root / stem
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"part-{index:05d}.parquet"
    path = directory / filename
    table = pa.Table.from_pylist(rows, schema=schema)
    size = write_table_atomic(
        table,
        path,
        expected_rows=len(rows),
        expected_schema=schema,
    )
    return {
        "path": f"{stem}/{filename}",
        "row_count": len(rows),
        "bytes": size,
        "sha256": file_sha256(path),
    }


def export_labeled_inventory(
    inventory_id: str,
    labelset_id: str | None,
    annotations_path: str | Path,
    *,
    batch_size: int = 5_000,
) -> dict[str, Any]:
    """Join an annotation JSONL file to the inventory and publish Parquet."""
    inventory_id = safe_id(inventory_id, "inventory_id")
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    root = resolve_paths().acceptance_root / "reflow-prose" / inventory_id
    inventory_root = root / "inventory"
    inventory_manifest_path = inventory_root / "manifest.json"
    if not inventory_manifest_path.is_file():
        raise FileNotFoundError(
            f"inventory manifest not found: {inventory_manifest_path}"
        )
    inventory_manifest = json.loads(inventory_manifest_path.read_text(encoding="utf-8"))
    annotations_path = Path(annotations_path).expanduser().resolve()
    if labelset_id is None:
        labelset_id = "labels-" + file_sha256(annotations_path)[:16]
    labelset_id = safe_id(labelset_id, "labelset_id")
    annotations = _load_annotations(annotations_path)
    template_path = inventory_root / "annotation_template.jsonl"
    required_ids = {row["block_id"] for row in jsonl_records(template_path)}
    missing = required_ids - annotations.keys()
    unknown = annotations.keys() - required_ids
    if missing or unknown:
        raise ValueError(
            f"annotation coverage mismatch: missing={len(missing)}, unknown={len(unknown)}"
        )

    output_root = root / "labels" / labelset_id
    if output_root.exists():
        raise FileExistsError(f"immutable label set already exists: {output_root}")
    output_root.mkdir(parents=True)
    block_files: list[dict[str, Any]] = []
    token_files: list[dict[str, Any]] = []
    label_counts: dict[str, int] = defaultdict(int)
    block_count = token_count = 0

    for source_key, destination, schema, is_block in (
        ("blocks", "blocks", BLOCK_SCHEMA, True),
        ("tokens", "tokens", TOKEN_SCHEMA, False),
    ):
        output_files = block_files if is_block else token_files
        for source_info in inventory_manifest["files"][source_key]:
            source_path = inventory_root / source_info["path"]
            if file_sha256(source_path) != source_info["sha256"]:
                raise ValueError(f"inventory shard hash mismatch: {source_path}")
            source_table = pq.read_table(source_path, schema=schema)
            source_rows = source_table.to_pylist()
            for offset in range(0, len(source_rows), batch_size):
                rows = source_rows[offset : offset + batch_size]
                for row in rows:
                    annotation = annotations.get(row["block_id"])
                    if annotation is None:
                        continue
                    row["gold_label"] = annotation["label"]
                    if is_block:
                        row["label_rationale"] = annotation["rationale"].strip()
                        label_counts[row["gold_label"]] += 1
                output_files.append(
                    _write_labeled_shard(
                        output_root,
                        destination,
                        schema,
                        rows,
                        len(output_files),
                    )
                )
                if is_block:
                    block_count += len(rows)
                else:
                    token_count += len(rows)

    annotations_output = output_root / "annotations.jsonl"
    canonical_annotations = (
        "\n".join(
            json.dumps(annotations[key], sort_keys=True, ensure_ascii=False)
            for key in sorted(annotations)
        )
        + "\n"
    )
    annotation_bytes = atomic_write_text(annotations_output, canonical_annotations)
    result = {
        "inventory_id": inventory_id,
        "labelset_id": labelset_id,
        "schema_version": SCHEMA_VERSION,
        "feature_version": inventory_manifest["feature_version"],
        "inventory_manifest_sha256": file_sha256(inventory_manifest_path),
        "input_annotations_sha256": file_sha256(annotations_path),
        "block_row_count": block_count,
        "token_row_count": token_count,
        "annotation_count": len(annotations),
        "label_counts": dict(sorted(label_counts.items())),
        "files": {
            "blocks": block_files,
            "tokens": token_files,
            "annotations": {
                "path": "annotations.jsonl",
                "row_count": len(annotations),
                "bytes": annotation_bytes,
                "sha256": file_sha256(annotations_output),
            },
        },
    }
    atomic_write_json(output_root / "manifest.json", result)
    return result


__all__ = ["export_labeled_inventory"]
