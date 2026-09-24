"""Build the block/token inventory from verified normalized review outputs."""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from defs import tables as defs_tables
from defs.runtime.paths import resolve_paths
from defs.sec_forms import page_markers
from defs.sec_forms.cover import reflow as cover_reflow
from defs.storage import (
    atomic_write_json,
    atomic_write_text,
    file_sha256,
    pa,
    write_table_atomic,
)
from defs.taxonomy.components.financials import reflow as financial_reflow
from defs.text import patterns as text_patterns
from defs.text import signatures as text_signatures
from defs.text.reflow import classifier as reflow_classifier
from defs.text.reflow import engine as reflow_engine
from defs.text.reflow import features as reflow_features

from . import analysis_export, analysis_features, analysis_records
from .analysis_features import (
    BLOCK_SCHEMA,
    FEATURE_VERSION,
    SCHEMA_VERSION,
    TOKEN_SCHEMA,
    digest,
    jsonl_records,
    safe_id,
)
from .analysis_records import analysis_policy, document_records


def _review_manifest(review_root: Path) -> tuple[list[dict[str, Any]], str]:
    path = review_root / "review_manifest.jsonl"
    if not path.is_file():
        raise FileNotFoundError(f"review manifest not found: {path}")
    records = list(jsonl_records(path))
    identifiers = [str(row.get("document_id", "")) for row in records]
    if any(not value for value in identifiers) or len(identifiers) != len(
        set(identifiers)
    ):
        raise ValueError("review manifest has missing or duplicate document IDs")
    records.sort(key=lambda row: str(row["document_id"]))
    return records, file_sha256(path)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> tuple[int, int]:
    lines = [json.dumps(row, sort_keys=True, ensure_ascii=False) for row in rows]
    text = "\n".join(lines) + ("\n" if lines else "")
    return len(lines), atomic_write_text(path, text)


def _flush_shard(
    root: Path,
    stem: str,
    schema,
    rows: list[dict[str, Any]],
    index: int,
) -> dict[str, Any]:
    directory = root / stem
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


def _code_provenance() -> dict[str, Any]:
    repository_root = Path(__file__).resolve().parents[3]
    modules = (
        sys.modules[__name__],
        analysis_export,
        analysis_features,
        analysis_records,
        reflow_classifier,
        reflow_engine,
        reflow_features,
        defs_tables.protection,
        defs_tables.structural,
        defs_tables.table_policy,
        text_patterns,
        text_signatures,
        cover_reflow,
        page_markers,
        financial_reflow,
    )
    code_hashes = {
        module.__name__: file_sha256(Path(module.__file__))
        for module in modules
        if getattr(module, "__file__", None) is not None
        and Path(module.__file__).is_file()
    }
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        revision = "unavailable"
        status = ""
    return {
        "git_revision": revision,
        "working_tree_dirty": bool(status),
        "working_tree_status_sha256": digest(status),
        "code_file_sha256": code_hashes,
        "code_fingerprint": digest(
            "\n".join(f"{path}:{code_hashes[path]}" for path in sorted(code_hashes))
        ),
    }


def build_inventory(
    review_root: str | Path,
    inventory_id: str | None = None,
    *,
    controls_per_role_per_document: int = 2,
    block_batch_size: int = 5_000,
    token_batch_size: int = 50_000,
) -> dict[str, Any]:
    """Build an immutable, unlabeled Parquet inventory from review outputs."""
    if (
        controls_per_role_per_document < 0
        or block_batch_size < 1
        or token_batch_size < 1
    ):
        raise ValueError("control and batch sizes must be non-negative/positive")
    review_root = Path(review_root).expanduser().resolve()
    manifest_rows, review_manifest_sha = _review_manifest(review_root)
    code_metadata = _code_provenance()
    if inventory_id is None:
        inventory_id = (
            "inventory-"
            + digest(
                f"{review_manifest_sha}\0{FEATURE_VERSION}\0{SCHEMA_VERSION}"
                f"\0{code_metadata['code_fingerprint']}"
            )[:16]
        )
    inventory_id = safe_id(inventory_id, "inventory_id")
    root = resolve_paths().acceptance_root / "reflow-prose" / inventory_id
    if root.exists():
        raise FileExistsError(f"immutable inventory already exists: {root}")
    inventory_root = root / "inventory"
    inventory_root.mkdir(parents=True, exist_ok=True)

    block_batch: list[dict[str, Any]] = []
    token_batch: list[dict[str, Any]] = []
    block_files: list[dict[str, Any]] = []
    token_files: list[dict[str, Any]] = []
    templates: list[dict[str, Any]] = []
    block_count = token_count = 0
    role_counts: Counter[str] = Counter()
    prose_dominant_preserve_count = 0
    policy = analysis_policy()

    def flush_blocks() -> None:
        nonlocal block_batch, block_count
        if block_batch:
            block_files.append(
                _flush_shard(
                    inventory_root,
                    "blocks",
                    BLOCK_SCHEMA,
                    block_batch,
                    len(block_files),
                )
            )
            block_count += len(block_batch)
            block_batch = []

    def flush_tokens() -> None:
        nonlocal token_batch, token_count
        if token_batch:
            token_files.append(
                _flush_shard(
                    inventory_root,
                    "tokens",
                    TOKEN_SCHEMA,
                    token_batch,
                    len(token_files),
                )
            )
            token_count += len(token_batch)
            token_batch = []

    for manifest_row in manifest_rows:
        document_id = safe_id(str(manifest_row["document_id"]), "document_id")
        case_dir = review_root / "cases" / document_id
        text_path = case_dir / f"{document_id}.txt"
        metadata_path = case_dir / f"{document_id}.metadata.json"
        raw = text_path.read_bytes()
        output_sha = digest(raw)
        if output_sha != str(manifest_row.get("current_output_sha256", "")):
            raise ValueError(f"current output hash mismatch for {document_id}")
        text = raw.decode("utf-8")
        metadata = (
            json.loads(metadata_path.read_text(encoding="utf-8"))
            if metadata_path.is_file()
            else {}
        )
        rows, annotation_rows, selected_tokens = document_records(
            manifest_row,
            text,
            metadata,
            output_sha,
            policy,
            controls_per_role_per_document,
        )
        role_counts.update(row["control_role"] for row in rows)
        prose_dominant_preserve_count += sum(
            row["classifier_action"] == "preserve"
            and "prose_dominant_numeric_alignment" in row["classifier_evidence"]
            for row in rows
        )
        templates.extend(annotation_rows)
        block_batch.extend(rows)
        token_batch.extend(selected_tokens)
        while len(block_batch) >= block_batch_size:
            chunk = block_batch[:block_batch_size]
            block_batch = block_batch[block_batch_size:]
            block_files.append(
                _flush_shard(
                    inventory_root, "blocks", BLOCK_SCHEMA, chunk, len(block_files)
                )
            )
            block_count += len(chunk)
        while len(token_batch) >= token_batch_size:
            chunk = token_batch[:token_batch_size]
            token_batch = token_batch[token_batch_size:]
            token_files.append(
                _flush_shard(
                    inventory_root, "tokens", TOKEN_SCHEMA, chunk, len(token_files)
                )
            )
            token_count += len(chunk)

    flush_blocks()
    flush_tokens()
    templates.sort(key=lambda row: row["block_id"])
    template_path = inventory_root / "annotation_template.jsonl"
    template_count, template_bytes = _write_jsonl(template_path, templates)
    summary = {
        "inventory_id": inventory_id,
        "schema_version": SCHEMA_VERSION,
        "feature_version": FEATURE_VERSION,
        "review_manifest_sha256": review_manifest_sha,
        "code": code_metadata,
        "review_document_count": len(manifest_rows),
        "block_row_count": block_count,
        "token_row_count": token_count,
        "annotation_required_count": template_count,
        "prose_dominant_preserve_count": prose_dominant_preserve_count,
        "protected_table_span_count": role_counts["protected_table_control"],
        "protected_signature_span_count": role_counts["protected_signature_control"],
        "control_role_counts": dict(sorted(role_counts.items())),
        "controls_per_role_per_document": controls_per_role_per_document,
        "analysis_policy": {
            "unwrap_pre_body_prose": True,
            "relax_prose_layout_gaps": True,
            "unwrap_bullet_continuations": True,
            "body_start_line": 0,
            "page_analysis": False,
        },
        "schemas": {
            "blocks": [
                {"name": field.name, "type": str(field.type)} for field in BLOCK_SCHEMA
            ],
            "tokens": [
                {"name": field.name, "type": str(field.type)} for field in TOKEN_SCHEMA
            ],
        },
        "files": {
            "blocks": block_files,
            "tokens": token_files,
            "annotation_template": {
                "path": "annotation_template.jsonl",
                "row_count": template_count,
                "bytes": template_bytes,
                "sha256": file_sha256(template_path),
            },
        },
    }
    atomic_write_json(inventory_root / "manifest.json", summary)
    return summary


__all__ = ["analysis_policy", "build_inventory"]
