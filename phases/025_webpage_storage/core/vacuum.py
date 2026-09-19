"""Parallel normalized-document snapshot vacuum and dependency-aware purge."""

from __future__ import annotations

import hashlib
import os
import shutil
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from defs.runtime.artifacts import (
    list_snapshots,
    make_snapshot_manifest,
    publish_snapshot_manifest,
)

from .snapshot import (
    DATASET,
    PHASE,
    NormalizedPayload,
    ProjectedOccurrence,
    SnapshotReader,
    _logical_fingerprint,
    filing_quarter,
    snapshot_id,
    write_quarter_parts,
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


def _effective_rows(
    root: Path, snapshot_ids: set[str], workers: int | None = None
) -> list[ProjectedOccurrence]:
    readers = [SnapshotReader(root, value) for value in sorted(snapshot_ids)]
    grouped: dict[tuple[int, str], list[tuple[SnapshotReader, dict]]] = defaultdict(
        list
    )
    for reader in readers:
        for row in reader.index_rows():
            grouped[filing_quarter(row["filing_date"])].append((reader, row))
    worker_count = max(1, workers or (os.cpu_count() or 1))
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = [pool.submit(_effective_quarter, item) for item in grouped.values()]
        result = [row for future in futures for row in future.result()]
    return result


def _effective_quarter(
    item: list[tuple[SnapshotReader, dict]],
) -> list[ProjectedOccurrence]:
    payload_requests: dict[int, tuple[SnapshotReader, list[dict]]] = {}
    for reader, row in item:
        key = id(reader)
        if key not in payload_requests:
            payload_requests[key] = (reader, [])
        payload_requests[key][1].append(row)
    payloads: dict[str, dict] = {}
    for reader, rows in payload_requests.values():
        payloads.update({str(row["doc_id"]): row for row in reader.payload_rows(rows)})
    occurrences: dict[str, ProjectedOccurrence] = {}
    content_by_doc: dict[str, str] = {}
    for _, row in item:
        doc_id = str(row["doc_id"])
        payload_row = payloads.get(doc_id)
        if payload_row is None:
            raise ValueError(f"missing payload for doc_id {doc_id}")
        clean_text = str(payload_row["clean_text"])
        payload = NormalizedPayload(
            doc_id,
            clean_text,
            hashlib.sha256(clean_text.encode("utf-8")).hexdigest(),
        )
        year, quarter = filing_quarter(row["filing_date"])
        candidate = ProjectedOccurrence(
            {key: row[key] for key in row if key != "payload_file"},
            payload,
            year,
            quarter,
        )
        existing = occurrences.get(str(row["occurrence_id"]))
        if existing is not None and existing.row != candidate.row:
            raise ValueError(f"conflicting occurrence {row['occurrence_id']}")
        occurrences[str(row["occurrence_id"])] = candidate
        prior_text = content_by_doc.get(doc_id)
        if prior_text is not None and prior_text != clean_text:
            raise ValueError(f"conflicting normalized content for doc_id {doc_id}")
        content_by_doc[doc_id] = clean_text
    return list(occurrences.values())


def vacuum_snapshots(
    *,
    artifacts_root: str | Path,
    snapshot_ids: list[str] | None = None,
    include_all: bool = False,
    workers: int | None = None,
    target_bytes: int = 96 * 1024 * 1024,
    purge_sources: bool = False,
    purge_dependency_closure: bool = False,
) -> dict:
    """Materialize selected snapshots in parallel and optionally purge sources."""
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
    worker_count = max(1, workers or (os.cpu_count() or 1))
    rows = _effective_rows(root, selected, worker_count)
    schema_version = ":".join(
        sorted({str(manifest.get("schema_version", "1")) for manifest in manifests})
    )
    logical = _logical_fingerprint(
        [row.row for row in rows],
        list({row.payload.doc_id: row.payload for row in rows}.values()),
    )
    physical_id = snapshot_id(
        operation="vacuum",
        source_snapshot_ids=selected,
        artifact_hashes=[logical],
        schema_version=schema_version,
    )
    grouped: dict[tuple[int, str], list[ProjectedOccurrence]] = defaultdict(list)
    for row in rows:
        grouped[(row.year, row.quarter)].append(row)

    def build(item: tuple[tuple[int, str], list[ProjectedOccurrence]]) -> list[dict]:
        (year, quarter), quarter_rows = item
        return write_quarter_parts(
            root=root,
            snapshot=physical_id,
            year=year,
            quarter=quarter,
            occurrences=quarter_rows,
            target_bytes=target_bytes,
        )

    parts: list[dict] = []
    snapshot_dir = root / "manifests" / PHASE / DATASET / "snapshots" / physical_id
    try:
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            futures = [pool.submit(build, item) for item in sorted(grouped.items())]
            for future in futures:
                parts.extend(future.result())
    except Exception:
        shutil.rmtree(snapshot_dir, ignore_errors=True)
        raise
    parts.sort(key=lambda part: str(part["path"]))
    manifest = make_snapshot_manifest(
        snapshot_id=physical_id,
        schema_version=schema_version,
        resolved_parts=parts,
        added_parts=parts,
        source_snapshot_ids=sorted(selected),
        dataset=DATASET,
        phase=PHASE,
        effective_cik_count=len(rows),
        effective_input_fingerprint=logical,
        provenance={
            "operation": "vacuum",
            "logical_fingerprint": logical,
            "merged_from": sorted(selected),
        },
    )
    manifest["logical_fingerprint"] = logical
    manifest["merged_from"] = sorted(selected)
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
    return manifest


__all__ = ["vacuum_snapshots"]
