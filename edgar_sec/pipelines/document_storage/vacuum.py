"""Cross-run snapshot consolidation.

A corpus is built by many partial runs, each publishing its own snapshot. Read as
N independent datasets, every consumer must union, dedupe, and re-derive fiscal
quarters itself. Consolidation does that once, and guarantees:

- **Source precedence is the caller's order.** The later-listed source wins when
  two describe the same document, so the outcome is reproducible.
- **Fiscal quarters are re-derived here.** ``filing_year`` and ``filing_quarter``
  are computed at consolidation time, so snapshots written months apart by
  different code versions land in the same partitioning.
- **Differing text is refused, not resolved.** Precedence could discard one side,
  but accepting that a document's text changed is not a decision consolidation
  may make for the caller.
- **Sources are immutable, purge is dependency-aware.** A source is deleted only
  once nothing retained references its parts, which
  :func:`expand_dependency_closure` establishes before anything is removed.

Quarters run on threads over one shared DuckDB relation, each with its own
connection, bounding per-quarter memory by batch size rather than corpus size.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from edgar_sec.foundation.hashing import sha256_bytes
from edgar_sec.foundation.runtime.memory import reclaim
from edgar_sec.foundation.runtime.paths import DOCUMENTS_DATASET
from edgar_sec.foundation.runtime.resources import RuntimeResourceProfile
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.duckdb import connect
from edgar_sec.infra.storage.manifests import (
    MANIFEST_NAME,
    PART_KIND_INDEX,
    PART_KIND_PAYLOAD,
    SnapshotPart,
    SnapshotReader,
    dependents_of,
    expand_dependency_closure,
    list_snapshots,
    now_iso,
    snapshot_dir,
    snapshot_identity,
    write_manifest,
)
from edgar_sec.pipelines.document_storage.parts import (
    PlannedPart,
    plan_parts,
    quarter_path,
    relation_for_parts,
    validate_part_paths,
    write_index_part,
    write_payload_part,
)
from edgar_sec.pipelines.document_storage.paths import DOCUMENTS_PHASE
from edgar_sec.pipelines.document_storage.queries import (
    effective_quarter_batches,
    effective_quarter_index_rows,
    effective_snapshot_relations,
    ranked_union_relations,
    relation_group_keys,
    relation_payload_conflicts,
)

log = logging.getLogger("document_storage.vacuum")

#: Default part budget. Chosen so a part is comfortably larger than DuckDB's
#: row-group size and small enough that many parts can be open during a read.
DEFAULT_TARGET_BYTES = 96 * 1024 * 1024
#: Registered as ``documents.payload_target_bytes`` in the settings registry,
#: so the value is env-overridable like every other batch size. This module is
#: the authority for the value; tests/pipelines/document_storage/test_settings_contract.py
#: pins the pair.


class VacuumError(RuntimeError):
    """Snapshots could not be consolidated."""


@dataclass(frozen=True, slots=True)
class QuarterResult:
    """What materializing one fiscal quarter produced."""

    year: int
    quarter: str
    parts: tuple[SnapshotPart, ...]
    index_rows: int
    payload_count: int
    digest: str


def _source_manifests(
    snapshots_root: Path, snapshot_ids: Sequence[str] | None, include_all: bool
) -> list[dict[str, Any]]:
    """Resolve the manifests to consolidate."""
    if include_all:
        selected = [
            str(item["snapshot_id"])
            for item in list_snapshots(snapshots_root)
            if item.get("snapshot_id")
        ]
    else:
        selected = [str(item) for item in (snapshot_ids or ())]
    if not selected:
        raise VacuumError("vacuum requires snapshot ids or include_all")
    return [
        SnapshotReader(snapshots_root, snapshot_id).manifest
        for snapshot_id in sorted(set(selected))
    ]


def _part_relation(
    snapshots_root: Path, manifests: Sequence[dict[str, Any]], kind: str
) -> str:
    """Build a ranked union relation over one kind of part across all sources.

    Part paths are validated before interpolation: a manifest is a file on disk,
    and a path is about to be spliced into a SQL string.
    """
    relations: list[str] = []
    for manifest in manifests:
        snapshot_id = str(manifest.get("snapshot_id") or "")
        parts = [
            SnapshotPart.from_dict(row)
            for row in manifest.get("resolved_parts", ())
            if str(row.get("kind")) == kind
        ]
        if not parts:
            continue
        # Part paths are relative to their own snapshot, so the relation is built
        # per source rather than over one shared root.
        base = snapshot_dir(snapshots_root, snapshot_id)
        validate_part_paths(parts, base)
        relations.append(relation_for_parts(parts, base))
    if not relations:
        raise VacuumError(f"selected snapshots contain no {kind} parts")
    return ranked_union_relations(relations)


def effective_relations(
    snapshots_root: Path, manifests: Sequence[dict[str, Any]]
) -> tuple[str, str]:
    """Return the deduplicated index and payload relations for a consolidation."""
    return effective_snapshot_relations(
        _part_relation(snapshots_root, manifests, PART_KIND_INDEX),
        _part_relation(snapshots_root, manifests, PART_KIND_PAYLOAD),
    )


def validate_payload_conflicts(
    connection: Any, raw_payload_relation: str, *, batch_size: int = 100
) -> None:
    """Raise when two sources disagree about a document's normalized text."""
    conflicts = [
        str(row["doc_id"])
        for batch in relation_payload_conflicts(
            connection, raw_payload_relation, batch_size=batch_size
        )
        for row in batch
    ]
    if conflicts:
        preview = ", ".join(sorted(conflicts)[:5])
        extra = f" (+{len(conflicts) - 5} more)" if len(conflicts) > 5 else ""
        raise VacuumError(
            f"conflicting normalized content for doc_id(s): {preview}{extra}"
        )


def quarter_keys(
    connection: Any, effective_index: str, *, batch_size: int = 256
) -> list[tuple[int, str]]:
    """Return every fiscal quarter present in the effective index."""
    return [
        (int(row["filing_year"]), str(row["filing_quarter"]))
        for batch in relation_group_keys(
            connection,
            effective_index,
            columns=("filing_year", "filing_quarter"),
            batch_size=batch_size,
        )
        for row in batch
    ]


def index_part_for(
    year: int, quarter: str, rows: Sequence[dict[str, Any]]
) -> PlannedPart:
    """Return the single index part covering one quarter.

    Index rows are metadata: roughly an order of magnitude smaller than the text
    they point at, so byte-budgeting them would split a quarter's index across
    parts for no read benefit while making every reader do more work.
    """
    return PlannedPart(
        path=quarter_path(year, quarter, PART_KIND_INDEX),
        kind=PART_KIND_INDEX,
        doc_ids=tuple(str(row["doc_id"]) for row in rows),
        estimated_bytes=sum(int(row.get("byte_size") or 0) for row in rows),
    )


def _vacuum_quarter(
    *,
    snapshots_root: Path,
    snapshot_id: str,
    effective_index: str,
    effective_payload: str,
    year: int,
    quarter: str,
    target_bytes: int,
    batch_size: int,
    profile: RuntimeResourceProfile | None,
    progress: Callable[[dict[str, Any]], None] | None,
) -> QuarterResult:
    """Materialize one quarter: plan parts, then stream payloads into them."""
    connection = connect(profile)
    target_dir = snapshot_dir(snapshots_root, snapshot_id)
    hasher = hashlib.sha256()
    try:
        # Pass 1: metadata only. Reads the index for the quarter, records each
        # document's byte size, and releases the batch before planning, so the
        # planner never holds text.
        index_rows: list[dict[str, Any]] = []
        doc_sizes: dict[str, int] = {}
        for batch in effective_quarter_index_rows(
            connection,
            effective_index,
            year=year,
            quarter=quarter,
            batch_size=batch_size,
        ):
            for row in batch:
                record = dict(row)
                record.pop("payload_file", None)
                index_rows.append(record)
                doc_sizes.setdefault(str(row["doc_id"]), int(row["byte_size"] or 0))
            del batch
            reclaim()
        if not index_rows:
            return QuarterResult(
                year, quarter, (), 0, 0, hashlib.sha256(b"").hexdigest()
            )

        # Pass 2: plan by document byte size, then read one doc range per part.
        planned = plan_parts(
            sorted(doc_sizes.items()),
            year=year,
            quarter=quarter,
            target_bytes=target_bytes,
            kind=PART_KIND_PAYLOAD,
        )
        doc_to_part = {doc_id: part.path for part in planned for doc_id in part.doc_ids}
        parts: list[SnapshotPart] = []
        for part in planned:
            texts = _stream_payload_texts(
                connection,
                effective_index,
                effective_payload,
                year=year,
                quarter=quarter,
                part=part,
                batch_size=batch_size,
                hasher=hasher,
            )
            missing = [doc_id for doc_id in part.doc_ids if doc_id not in texts]
            if missing:
                raise VacuumError(
                    f"missing payload for doc_id(s) in {year}-{quarter}: "
                    + ", ".join(missing[:5])
                )
            parts.append(
                write_payload_part(
                    target_dir,
                    part,
                    [(doc_id, texts[doc_id]) for doc_id in part.doc_ids],
                )
            )
            del texts
            reclaim()
            if progress is not None:
                progress(
                    {
                        "type": "part_written",
                        "year": year,
                        "quarter": quarter,
                        "payloads": len(part.doc_ids),
                        "path": part.path,
                    }
                )

        for row in index_rows:
            row["payload_file"] = doc_to_part[str(row["doc_id"])]
        index_rows.sort(key=lambda row: str(row["doc_id"]))
        parts.append(
            write_index_part(
                target_dir,
                index_part_for(year, quarter, index_rows),
                index_rows,
            )
        )

        if progress is not None:
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
        return QuarterResult(
            year=year,
            quarter=quarter,
            parts=tuple(parts),
            index_rows=len(index_rows),
            payload_count=len(doc_sizes),
            digest=hasher.hexdigest(),
        )
    finally:
        connection.close()


def _stream_payload_texts(
    connection: Any,
    effective_index: str,
    effective_payload: str,
    *,
    year: int,
    quarter: str,
    part: PlannedPart,
    batch_size: int,
    hasher: hashlib._Hash,
) -> dict[str, str]:
    """Read one doc range's payloads, updating the logical digest as it goes.

    The digest is computed over the *content* being written, not over the part
    files, so it identifies what the snapshot contains rather than how the bytes
    happened to be laid out.
    """
    texts: dict[str, str] = {}
    for batch in effective_quarter_batches(
        connection,
        effective_index,
        effective_payload,
        year=year,
        quarter=quarter,
        doc_lo=part.doc_ids[0],
        doc_hi=part.doc_ids[-1],
        batch_size=batch_size,
    ):
        for row in batch:
            clean_text = str(row.get("clean_text") or "")
            doc_id = str(row["doc_id"])
            texts.setdefault(doc_id, clean_text)
            hasher.update(
                canonical_json(
                    {
                        "doc_id": doc_id,
                        "payload_sha256": sha256_bytes(clean_text.encode("utf-8")),
                    }
                ).encode("utf-8")
            )
        del batch
        reclaim()
    return texts


def vacuum_snapshots(
    *,
    snapshots_root: Path,
    snapshot_ids: Sequence[str] | None = None,
    include_all: bool = False,
    workers: int | None = None,
    target_bytes: int = DEFAULT_TARGET_BYTES,
    purge_sources: bool = False,
    purge_dependency_closure: bool = False,
    batch_size: int = 4096,
    profile: RuntimeResourceProfile | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Consolidate snapshots into one canonical snapshot.

    Args:
        snapshots_root: the dataset's published root (``ProjectPaths
            .documents_root``), holding every snapshot and the current pointer.
        snapshot_ids: snapshots to consolidate; ignored when ``include_all``.
        include_all: consolidate every published snapshot.
        workers: quarter concurrency; defaults to 1.
        target_bytes: per-part byte budget.
        purge_sources: delete the sources once consolidation succeeds. Refuses
            when a retained snapshot still references a source part.
        purge_dependency_closure: instead of refusing, consolidate the whole
            dependency closure so the purge becomes safe.
        batch_size: rows per fetched batch.
        profile: pre-resolved cgroup-aware resource profile.
        progress: optional per-stage callback.

    Returns:
        The published manifest, including its snapshot id and part list.
    """
    root = Path(snapshots_root)
    manifests = _source_manifests(root, snapshot_ids, include_all)
    selected = {str(manifest["snapshot_id"]) for manifest in manifests}

    if purge_dependency_closure:
        selected = expand_dependency_closure(root, selected)
        manifests = [
            SnapshotReader(root, snapshot_id).manifest
            for snapshot_id in sorted(selected)
        ]
    elif purge_sources:
        blocked = sorted(
            {
                dependent
                for values in dependents_of(list_snapshots(root), selected).values()
                for dependent in values
            }
        )
        if blocked:
            raise VacuumError(
                "cannot purge snapshots referenced by retained snapshots: "
                + ", ".join(blocked)
            )

    raw_payload = _part_relation(root, manifests, PART_KIND_PAYLOAD)
    effective_index, effective_payload = effective_relations(root, manifests)

    validation = connect(profile)
    try:
        validate_payload_conflicts(validation, raw_payload)
        quarters = quarter_keys(validation, effective_index)
    finally:
        validation.close()

    if progress is not None:
        progress(
            {
                "type": "sources_resolved",
                "snapshot_ids": sorted(selected),
                "quarter_count": len(quarters),
            }
        )

    schema_version = ":".join(
        sorted({str(manifest.get("schema_version", "1")) for manifest in manifests})
    )
    physical_id = snapshot_identity(
        operation="vacuum",
        source_snapshot_ids=selected,
        artifact_hashes={
            str(manifest.get("logical_fingerprint") or manifest.get("snapshot_id"))
            for manifest in manifests
        },
        schema_version=schema_version,
    )

    # Refuse before writing anything. The derived id is deterministic, so a repeat
    # consolidation of the same sources lands here; writing parts first would
    # overwrite an immutable snapshot's bytes before the refusal could fire.
    target_dir = snapshot_dir(root, physical_id)
    if (target_dir / MANIFEST_NAME).is_file():
        raise VacuumError(
            f"snapshot {physical_id} already exists; the same sources were "
            "already consolidated"
        )

    parts: list[SnapshotPart] = []
    row_count = 0
    payload_count = 0
    digests: list[str] = []
    try:
        with ThreadPoolExecutor(max_workers=max(1, workers or 1)) as pool:
            futures = {
                pool.submit(
                    _vacuum_quarter,
                    snapshots_root=root,
                    snapshot_id=physical_id,
                    effective_index=effective_index,
                    effective_payload=effective_payload,
                    year=year,
                    quarter=quarter,
                    target_bytes=target_bytes,
                    batch_size=max(1, batch_size),
                    profile=profile,
                    progress=progress,
                ): (year, quarter)
                for year, quarter in quarters
            }
            for future in as_completed(futures):
                result = future.result()
                parts.extend(result.parts)
                row_count += result.index_rows
                payload_count += result.payload_count
                digests.append(f"{result.year}:{result.quarter}:{result.digest}")
    except BaseException:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise

    parts.sort(key=lambda part: part.path)
    logical = sha256_bytes(canonical_json(sorted(digests)).encode("utf-8"))
    manifest: dict[str, Any] = {
        "snapshot_id": physical_id,
        "schema_version": schema_version,
        "resolved_parts": [part.to_dict() for part in parts],
        "source_snapshot_ids": sorted(selected),
        "dataset": DOCUMENTS_DATASET,
        "phase": DOCUMENTS_PHASE,
        "effective_index_rows": row_count,
        "effective_payload_count": payload_count,
        "logical_fingerprint": logical,
        "merged_from": sorted(selected),
        "created_at": now_iso(),
        "provenance": {
            "operation": "vacuum",
            "logical_fingerprint": logical,
            "merged_from": sorted(selected),
        },
    }

    write_manifest(
        root,
        manifest,
        dataset=DOCUMENTS_DATASET,
        phase=DOCUMENTS_PHASE,
        set_current=True,
    )

    if purge_sources or purge_dependency_closure:
        for source in sorted(selected):
            if source == physical_id:
                continue
            shutil.rmtree(snapshot_dir(root, source), ignore_errors=False)

    if progress is not None:
        progress(
            {
                "type": "publish_manifest",
                "snapshot_id": physical_id,
                "rows": row_count,
                "payloads": payload_count,
            }
        )
    return manifest


__all__ = [
    "DEFAULT_TARGET_BYTES",
    "QuarterResult",
    "VacuumError",
    "effective_relations",
    "index_part_for",
    "quarter_keys",
    "vacuum_snapshots",
    "validate_payload_conflicts",
]
