"""Parallel normalized-document snapshot vacuum and dependency-aware purge."""

from __future__ import annotations

import hashlib
import shutil
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from defs.runtime.artifacts import (
    list_snapshots,
    make_snapshot_manifest,
    publish_snapshot_manifest,
)
from defs.sql import make_sql_executor
from defs.storage import (
    FinalizedDataset,
    canonical_json,
    force_reclaim_memory,
)

from .queries import (
    effective_quarter_batches,
    effective_quarter_index_rows,
    effective_snapshot_relations,
    ranked_union_relations,
    relation_group_keys,
    relation_payload_conflicts,
)
from .snapshot import (
    DATASET,
    PHASE,
    SnapshotReader,
    _path_for,
    _write_payload_part,
    _write_quarter_index_part,
    plan_payload_parts,
    snapshot_id,
)


def _source_snapshots(
    root: Path,
    snapshot_ids: list[str] | None,
    include_all: bool,
) -> list[dict]:
    if include_all:
        available = list_snapshots(phase=PHASE, dataset=DATASET, artifacts_root=root)
        selected = [str(item["snapshot_id"]) for item in available]
    else:
        selected = list(snapshot_ids or [])
    if not selected:
        raise ValueError("vacuum requires --snapshots or --all")
    manifests = []
    for snapshot_id_value in sorted(set(selected)):
        reader = SnapshotReader(root, snapshot_id_value)
        manifests.append(reader.manifest)
    return manifests


def _referenced_by(manifests: list[dict], source_ids: set[str]) -> dict[str, set[str]]:
    source_parts = {
        str(part["path"])
        for manifest in manifests
        if str(manifest.get("snapshot_id")) in source_ids
        for part in manifest.get("resolved_parts", [])
    }
    dependents: dict[str, set[str]] = defaultdict(set)
    for manifest in manifests:
        snapshot = str(manifest.get("snapshot_id"))
        if snapshot in source_ids:
            continue
        for part in manifest.get("resolved_parts", []):
            if str(part.get("path")) in source_parts:
                for source in source_ids:
                    if any(
                        str(candidate.get("path")) == str(part.get("path"))
                        for candidate in next(
                            (
                                item.get("resolved_parts", [])
                                for item in manifests
                                if str(item.get("snapshot_id")) == source
                            ),
                            [],
                        )
                    ):
                        dependents[source].add(snapshot)
    return dependents


def _expand_dependency_closure(root: Path, selected: set[str]) -> set[str]:
    all_manifests = [
        item["manifest"]
        for item in list_snapshots(phase=PHASE, dataset=DATASET, artifacts_root=root)
    ]
    closure = set(selected)
    changed = True
    while changed:
        changed = False
        dependents = _referenced_by(all_manifests, closure)
        for values in dependents.values():
            before = len(closure)
            closure.update(values)
            changed |= len(closure) != before
    return closure


def _relation(root: Path, manifests: list[dict], kind: str) -> str:
    """Build a validated DuckDB relation over manifest-listed parts."""
    relations = []
    for manifest in manifests:
        parts = [
            part
            for part in manifest.get("resolved_parts", [])
            if part.get("kind") == kind
        ]
        if not parts:
            continue
        dataset = FinalizedDataset({"resolved_parts": parts}, artifacts_root=root)
        try:
            relations.append(dataset.relation)
        finally:
            dataset.close()
    if not relations:
        raise ValueError(f"selected snapshots contain no {kind} parts")
    return ranked_union_relations(relations)


def _effective_relations(root: Path, manifests: list[dict]) -> tuple[str, str]:
    index = _relation(root, manifests, "index")
    payload = _relation(root, manifests, "payload")
    return effective_snapshot_relations(index, payload)


def _validate_payload_conflicts(executor, effective_payload: str) -> None:
    rows = relation_payload_conflicts(executor, effective_payload)
    conflicts = [row["doc_id"] for batch in rows for row in batch]
    if conflicts:
        raise ValueError(
            "conflicting normalized content for doc_id(s): " + ", ".join(conflicts)
        )


def _quarter_keys(executor, effective_index: str) -> list[tuple[int, str]]:
    rows = relation_group_keys(
        executor,
        effective_index,
        columns=("filing_year", "filing_quarter"),
    )
    return [
        (int(row["filing_year"]), str(row["filing_quarter"]))
        for batch in rows
        for row in batch
    ]


def _vacuum_quarter(
    *,
    root: Path,
    snapshot_id_value: str,
    effective_index: str,
    effective_payload: str,
    year: int,
    quarter: str,
    target_bytes: int,
    batch_size: int,
    threads: int | None,
    memory_limit: str | None,
    temp_directory: str | Path | None,
    progress,
) -> tuple[list[dict], int, int, str]:
    """Materialize one quarter via a metadata plan and doc-bounded payload reads."""
    executor = make_sql_executor(
        dialect="duckdb",
        threads=threads,
        memory_limit=memory_limit,
        temp_directory=temp_directory,
    )
    logical_hasher = hashlib.sha256()
    try:
        # Pass 1: metadata-only index rows for the quarter; plan parts by byte_size.
        index_rows: list[dict] = []
        doc_sizes: dict[str, int] = {}
        for batch in effective_quarter_index_rows(
            executor,
            effective_index,
            year=year,
            quarter=quarter,
            batch_size=max(1, batch_size),
        ):
            for row in batch:
                row = dict(row)
                row.pop("payload_file", None)
                index_rows.append(row)
                doc_sizes.setdefault(str(row["doc_id"]), int(row["byte_size"]))
            del batch
            force_reclaim_memory()
        if not index_rows:
            return [], 0, 0, hashlib.sha256(b"").hexdigest()
        doc_sizes_by_quarter = {(year, quarter): sorted(doc_sizes.items())}
        planned_parts = plan_payload_parts(
            doc_sizes_by_quarter,
            root=root,
            snapshot=snapshot_id_value,
            target_bytes=target_bytes,
        )
        doc_payload_file = {
            doc_id: _path_for(root, part.path)
            for part in planned_parts
            for doc_id in part.doc_ids
        }
        # Pass 2: one doc-range payload read per planned part.
        parts: list[dict] = []
        for part in planned_parts:
            texts: dict[str, str] = {}
            doc_lo = part.doc_ids[0]
            doc_hi = part.doc_ids[-1]
            for rows in effective_quarter_batches(
                executor,
                effective_index,
                effective_payload,
                year=year,
                quarter=quarter,
                doc_lo=doc_lo,
                doc_hi=doc_hi,
                batch_size=max(1, batch_size),
            ):
                for row in rows:
                    clean_text = str(row.pop("clean_text"))
                    row.pop("payload_file", None)
                    doc_id = str(row["doc_id"])
                    if doc_id not in texts:
                        texts[doc_id] = clean_text
                    logical_hasher.update(
                        canonical_json(
                            {
                                "index": row,
                                "payload_sha256": hashlib.sha256(
                                    clean_text.encode("utf-8")
                                ).hexdigest(),
                            }
                        ).encode("utf-8")
                    )
                del rows
                force_reclaim_memory()
            missing = [doc_id for doc_id in part.doc_ids if doc_id not in texts]
            if missing:
                raise ValueError(
                    f"missing payload for doc_id(s): {', '.join(missing[:5])}"
                )
            payload_rows = [(doc_id, texts[doc_id]) for doc_id in part.doc_ids]
            parts.append(_write_payload_part(root, part, payload_rows))
            if progress:
                progress(
                    {
                        "type": "part_written",
                        "year": year,
                        "quarter": quarter,
                        "payloads": len(payload_rows),
                        "path": str(part.path),
                    }
                )
            del texts, payload_rows
            force_reclaim_memory()
        for row in index_rows:
            row["payload_file"] = doc_payload_file[str(row["doc_id"])]
        parts.append(
            _write_quarter_index_part(
                root, snapshot_id_value, year, quarter, index_rows
            )
        )
        if progress:
            progress(
                {
                    "type": "quarter_done",
                    "year": year,
                    "quarter": quarter,
                    "rows": len(index_rows),
                    "payloads": len(doc_sizes),
                    "parts": len(parts),
                }
            )
        return parts, len(index_rows), len(doc_sizes), logical_hasher.hexdigest()
    finally:
        executor.close()


def vacuum_snapshots(
    *,
    artifacts_root: str | Path,
    snapshot_ids: list[str] | None = None,
    include_all: bool = False,
    workers: int | None = None,
    target_bytes: int = 96 * 1024 * 1024,
    purge_sources: bool = False,
    purge_dependency_closure: bool = False,
    threads: int | None = None,
    memory_limit: str | None = None,
    temp_directory: str | Path | None = None,
    batch_size: int = 4096,
    progress=None,
) -> dict:
    """Materialize selected snapshots with bounded DuckDB quarter workers."""
    root = Path(artifacts_root).resolve()
    manifests = _source_snapshots(root, snapshot_ids, include_all)
    selected = {str(manifest["snapshot_id"]) for manifest in manifests}
    if purge_dependency_closure:
        selected = _expand_dependency_closure(root, selected)
        manifests = [
            SnapshotReader(root, snapshot_id_value).manifest
            for snapshot_id_value in sorted(selected)
        ]
    elif purge_sources:
        all_manifests = [
            item["manifest"]
            for item in list_snapshots(
                phase=PHASE, dataset=DATASET, artifacts_root=root
            )
        ]
        dependents = _referenced_by(all_manifests, selected)
        blocked = sorted({value for values in dependents.values() for value in values})
        if blocked:
            raise ValueError(
                "cannot purge snapshots referenced by retained snapshots: "
                + ", ".join(blocked)
            )
    worker_count = max(1, workers or 1)
    schema_version = ":".join(
        sorted({str(manifest.get("schema_version", "1")) for manifest in manifests})
    )
    raw_payload = _relation(root, manifests, "payload")
    effective_index, effective_payload = _effective_relations(root, manifests)
    validation_executor = make_sql_executor(
        dialect="duckdb",
        threads=threads,
        memory_limit=memory_limit,
        temp_directory=temp_directory,
    )
    try:
        _validate_payload_conflicts(validation_executor, raw_payload)
        quarters = _quarter_keys(validation_executor, effective_index)
    finally:
        validation_executor.close()
    if progress:
        progress(
            {
                "type": "vacuum_sources_resolved",
                "snapshot_ids": sorted(selected),
                "quarter_count": len(quarters),
            }
        )
    physical_id = snapshot_id(
        operation="vacuum",
        source_snapshot_ids=selected,
        artifact_hashes=sorted(
            str(manifest.get("logical_fingerprint", manifest.get("snapshot_id")))
            for manifest in manifests
        ),
        schema_version=schema_version,
    )
    parts: list[dict] = []
    row_count = 0
    payload_count = 0
    quarter_digests: list[str] = []
    snapshot_dir = root / "manifests" / PHASE / DATASET / "snapshots" / physical_id
    try:
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            future_map = {
                pool.submit(
                    _vacuum_quarter,
                    root=root,
                    snapshot_id_value=physical_id,
                    effective_index=effective_index,
                    effective_payload=effective_payload,
                    year=year,
                    quarter=quarter,
                    target_bytes=target_bytes,
                    batch_size=max(1, batch_size),
                    threads=threads,
                    memory_limit=memory_limit,
                    temp_directory=temp_directory,
                    progress=progress,
                ): (year, quarter)
                for year, quarter in quarters
            }
            for future in as_completed(future_map):
                year, quarter = future_map[future]
                quarter_parts, quarter_rows, quarter_payloads, digest = future.result()
                parts.extend(quarter_parts)
                row_count += quarter_rows
                payload_count += quarter_payloads
                quarter_digests.append(f"{year}:{quarter}:{digest}")
    except Exception:
        shutil.rmtree(snapshot_dir, ignore_errors=True)
        raise
    parts.sort(key=lambda part: str(part["path"]))
    logical = hashlib.sha256(
        canonical_json(sorted(quarter_digests)).encode("utf-8")
    ).hexdigest()
    manifest = make_snapshot_manifest(
        snapshot_id=physical_id,
        schema_version=schema_version,
        resolved_parts=parts,
        added_parts=parts,
        source_snapshot_ids=sorted(selected),
        dataset=DATASET,
        phase=PHASE,
        effective_cik_count=row_count,
        effective_input_fingerprint=logical,
        provenance={
            "operation": "vacuum",
            "logical_fingerprint": logical,
            "merged_from": sorted(selected),
        },
    )
    manifest["logical_fingerprint"] = logical
    manifest["merged_from"] = sorted(selected)
    manifest["effective_payload_count"] = payload_count
    try:
        publish_snapshot_manifest(
            manifest,
            artifacts_root=root,
            phase=PHASE,
            dataset=DATASET,
            set_current=True,
        )
    except Exception:
        shutil.rmtree(snapshot_dir, ignore_errors=True)
        raise
    if purge_sources or purge_dependency_closure:
        snapshots_dir = root / "manifests" / PHASE / DATASET / "snapshots"
        for source in sorted(selected):
            if source == physical_id:
                continue
            shutil.rmtree(snapshots_dir / source, ignore_errors=False)
    if progress:
        progress(
            {
                "type": "publish_manifest",
                "snapshot_id": physical_id,
                "rows": row_count,
                "payloads": payload_count,
            }
        )
    return manifest


__all__ = ["vacuum_snapshots"]
