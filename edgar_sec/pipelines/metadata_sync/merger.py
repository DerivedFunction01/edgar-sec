"""Coordinator merge: validate every chunk, then publish one snapshot.

The coordinator is the only component that writes published artifacts, and it
publishes only once every chunk has validated.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from edgar_sec.domain.submissions.schemas import SCHEMA_VERSION
from edgar_sec.foundation.hashing import file_sha256, sha256_bytes
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.manifest import (
    DAGNodeManifest,
    ParentRef,
    PartDescriptor,
)
from edgar_sec.infra.storage.duckdb import (
    connect,
    find_duplicate_keys,
    find_null_keys,
)
from edgar_sec.infra.storage.parquet import count_parquet_rows, read_parquet_schema

from .paths import PARTS_DIR_NAME, MetadataPaths, RunPaths
from .planner import Plan, utc_now_iso
from .roster import read_cik_index, write_cik_index
from .snapshot import SNAPSHOT_MANIFEST_VERSION
from .validation import find_duplicate_accessions

__all__ = [
    "MergeError",
    "MergeReport",
    "merge_chunks",
    "parts_digest",
    "publish_current_snapshot",
    "publish_parts",
    "publish_snapshot",
]


class MergeError(RuntimeError):
    """Merge rejected; the snapshot was not published."""


@dataclass(slots=True)
class MergeReport:
    """Result of one merge attempt."""

    snapshot_id: str
    output_path: str = ""
    cik_index_path: str = ""
    row_count: int = 0
    chunk_count: int = 0
    filing_record_count: int = 0
    artifact_sha256: str = ""
    cik_index_sha256: str = ""
    cik_count: int = 0
    plan_id: str = ""
    input_fingerprint: str = ""
    kind: str = "full"
    parent_snapshot_id: str = ""
    roster_id: str = ""
    delta_roster_id: str = ""
    schema_version: str = SCHEMA_VERSION
    manifest_version: str = SNAPSHOT_MANIFEST_VERSION
    sort_order: str = "chunk_order"
    parts: list[dict[str, Any]] = field(default_factory=list)
    parts_digest: str = ""
    merged_at: str = ""
    duplicate_accessions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def part_count(self) -> int:
        """Number of Parquet parts carrying this snapshot's rows."""
        return len(self.parts) or 1

    def to_dict(self) -> dict[str, Any]:
        """Serializable report for the snapshot manifest.
        ``output_path``/``artifact_sha256`` stay empty for a multipart snapshot on purpose,
        so a single-file reader fails loudly instead of ingesting a fraction.
        """
        manifest = {
            "snapshot_id": self.snapshot_id,
            "output_path": self.output_path,
            "cik_index_path": self.cik_index_path,
            "cik_index_sha256": self.cik_index_sha256,
            "cik_count": self.cik_count,
            "row_count": self.row_count,
            "chunk_count": self.chunk_count,
            "filing_record_count": self.filing_record_count,
            "artifact_sha256": self.artifact_sha256,
            "plan_id": self.plan_id,
            "input_fingerprint": self.input_fingerprint,
            "kind": self.kind,
            "parent_snapshot_id": self.parent_snapshot_id,
            "roster_id": self.roster_id,
            "delta_roster_id": self.delta_roster_id,
            "schema_version": self.schema_version,
            "merged_at": self.merged_at,
            "duplicate_accessions": self.duplicate_accessions,
            "warnings": self.warnings,
        }
        if self.parts:
            manifest["manifest_version"] = self.manifest_version
            manifest["part_count"] = len(self.parts)
            manifest["parts_digest"] = self.parts_digest
            manifest["sort_order"] = self.sort_order
            manifest["parts"] = self.parts
        return manifest


def _published_ciks(part_paths: tuple[Path, ...]) -> list[str]:
    """Read the CIK column of the published parts.
    Built from disk rather than the roster, so a short snapshot is visible here.
    """
    import pyarrow.parquet as pq

    ciks: list[str] = []
    for path in part_paths:
        table = pq.read_table(path, columns=["cik"])
        ciks.extend(str(value) for value in table.column("cik").to_pylist())
    return ciks


def parts_digest(parts: list[dict[str, Any]]) -> str:
    """One digest over the ordered part digests.
    Binds a pointer to the exact dataset without rehashing every part.
    """
    material = canonical_json([str(part["sha256"]) for part in parts]).encode("utf-8")
    return sha256_bytes(material)


def _safe_progress(
    progress: Callable[[dict[str, Any]], None] | None,
) -> Callable[[dict[str, Any]], None]:
    """Wrap a progress callback so presentation failure cannot fail a merge."""

    def emit(event: dict[str, Any]) -> None:
        if progress is None:
            return
        try:
            progress(event)
        except Exception:
            pass

    return emit


def _filing_record_count(paths: list[str]) -> int:
    import pyarrow.parquet as pq

    total = 0
    for path in paths:
        table = pq.read_table(path, columns=["filings"])
        total += sum(
            len(value) for value in table.column("filings").to_pylist() if value
        )
    return total


def validate_chunks(plan: Plan, run_paths: RunPaths) -> list[Path]:
    """Validate every planned chunk and return the ordered checkpoint paths."""
    chunk_ids = plan.chunk_ids()
    if sum(plan.chunk_length(chunk_id) for chunk_id in chunk_ids) != int(
        plan.row_count
    ):
        raise MergeError("plan chunks do not cover the planned CIK count")

    found: dict[int, Path] = {}
    for path in sorted(run_paths.chunk_dir.glob("chunk_*.parquet")):
        try:
            chunk_id = int(path.stem.split("_", 1)[1])
        except (IndexError, ValueError):
            continue
        found[chunk_id] = path

    foreign = set(found) - set(chunk_ids)
    if foreign:
        raise MergeError(
            f"merge rejected: chunk files outside the plan: {sorted(foreign)}"
        )
    missing = sorted(set(chunk_ids) - set(found))
    if missing:
        raise MergeError(f"merge rejected: missing chunk checkpoints: {missing}")

    fingerprint = plan.input_fingerprint
    for chunk_id in sorted(chunk_ids):
        path = found[chunk_id]
        if not read_parquet_schema(path).equals(plan_schema(), check_metadata=False):
            raise MergeError(
                f"merge rejected: chunk {chunk_id} schema drifted from the dataset contract"
            )
        rows = count_parquet_rows(path)
        if rows != plan.chunk_length(chunk_id):
            raise MergeError(
                f"merge rejected: chunk {chunk_id} row count {rows} "
                f"!= planned {plan.chunk_length(chunk_id)}"
            )

    import pyarrow.parquet as pq

    for chunk_id in sorted(chunk_ids):
        table = pq.read_table(
            found[chunk_id], columns=["cik", "input_fingerprint", "status"]
        )
        ciks = tuple(str(v) for v in table.column("cik").to_pylist())
        # One chunk's CIKs are read from the roster at a time; materializing
        # every chunk up front would hold the whole cohort for a coverage check.
        planned_ciks = plan.chunk_ciks(chunk_id)
        if set(ciks) != set(planned_ciks) or len(ciks) != len(planned_ciks):
            raise MergeError(
                f"merge rejected: chunk {chunk_id} CIK coverage differs from the plan"
            )
        if fingerprint:
            foreign_fingerprints = {
                value
                for value in table.column("input_fingerprint").to_pylist()
                if value and value != fingerprint
            }
            if foreign_fingerprints:
                raise MergeError(
                    f"merge rejected: chunk {chunk_id} carries a foreign input fingerprint"
                )
        bad_status = [
            value
            for value in table.column("status").to_pylist()
            if value not in ("ok", "partial", "failed")
        ]
        if bad_status:
            raise MergeError(
                f"merge rejected: chunk {chunk_id} contains non-terminal statuses: "
                f"{sorted(set(bad_status))}"
            )

    return [found[chunk_id] for chunk_id in sorted(found)]


def plan_schema():
    """Canonical dataset schema for chunk comparison."""
    from edgar_sec.domain.submissions.schemas import SUBMISSION_METADATA_SCHEMA

    return SUBMISSION_METADATA_SCHEMA


def publish_cik_index(
    report: MergeReport,
    metadata_paths: MetadataPaths,
    ciks: list[str],
) -> MergeReport:
    """Write the sorted distinct CIK index beside a published payload.
    Derived from the published rows, not from what was requested.
    """
    path = metadata_paths.snapshot_cik_index(report.snapshot_id)
    report.cik_index_path = str(path)
    report.cik_index_sha256 = write_cik_index(ciks, path)
    report.cik_count = len(read_cik_index(path))
    return report


def publish_parts(
    report: MergeReport,
    metadata_paths: MetadataPaths,
    sources: Sequence[tuple[str, Path]],
) -> tuple[Path, ...]:
    """Publish validated source files as a snapshot's ordered Parquet parts."""
    parts_dir = metadata_paths.snapshot_parts_dir(report.snapshot_id)
    parts_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir = metadata_paths.snapshot_dir(report.snapshot_id)
    published: list[Path] = []
    chunk_index = 0
    for index, (label, source) in enumerate(sources):
        if label.startswith("base:"):
            if not source.is_file():
                raise MergeError(f"ancestor part missing: {source}")
            rel_path = os.path.relpath(source, snapshot_dir)
            report.parts.append(
                {
                    "path": rel_path,
                    "part_index": index,
                    "source": label,
                    "row_count": count_parquet_rows(source),
                    "byte_count": source.stat().st_size,
                    "sha256": file_sha256(source),
                    "schema_version": report.schema_version,
                }
            )
            published.append(source)
            continue

        name = f"part-{chunk_index:05d}.parquet"
        chunk_index += 1
        destination = parts_dir / name
        shutil.copy2(source, destination)
        if not read_parquet_schema(destination).equals(
            plan_schema(), check_metadata=False
        ):
            destination.unlink(missing_ok=True)
            raise MergeError(
                f"merge rejected: published part {name} (from {label}) schema drifted "
                "from the dataset contract"
            )
        report.parts.append(
            {
                "path": f"{PARTS_DIR_NAME}/{name}",
                "part_index": index,
                "source": label,
                "row_count": count_parquet_rows(destination),
                "byte_count": destination.stat().st_size,
                "sha256": file_sha256(destination),
                "schema_version": report.schema_version,
            }
        )
        published.append(destination)
    return tuple(published)


def _publish_chunk_parts(
    report: MergeReport,
    metadata_paths: MetadataPaths,
    chunk_paths: list[Path],
) -> tuple[Path, ...]:
    return publish_parts(
        report,
        metadata_paths,
        [(f"chunk:{path.stem}", path) for path in chunk_paths],
    )


def merge_chunks(
    plan: Plan,
    run_paths: RunPaths,
    snapshot_id: str,
    *,
    lineage: dict[str, str] | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> MergeReport:
    """Validate all chunks and publish a sorted snapshot dataset.
    A delta plan is refused; a failing progress callback never aborts publication.
    """
    if plan.kind == "delta":
        raise MergeError(
            f"plan {plan.plan_id} is a delta plan over base {plan.parent_id or '?'}"
            " and cannot be merged on its own: a plain merge would publish only the"
            " delta and drop the base rows. Publish it with"
            " 'metadata augment --base-snapshot-id <base>'"
        )
    emit = _safe_progress(progress)
    emit({"type": "merge_start", "plan_id": plan.plan_id})
    chunk_paths = validate_chunks(plan, run_paths)
    str_paths = [str(path) for path in chunk_paths]
    recorded = {**plan.lineage(), **(lineage or {})}
    report = MergeReport(
        snapshot_id=snapshot_id,
        chunk_count=len(chunk_paths),
        plan_id=plan.plan_id,
        input_fingerprint=plan.input_fingerprint,
        kind=plan.kind,
        parent_snapshot_id=plan.parent_id or recorded.get("parent_snapshot_id", ""),
        roster_id=plan.roster.roster_id,
        delta_roster_id=recorded.get("delta_roster_id", ""),
        merged_at=utc_now_iso(),
    )
    emit({"type": "chunks_validated", "chunks": len(chunk_paths)})

    con = connect()
    try:
        null_keys = find_null_keys(con, str_paths, "cik")
        if null_keys:
            raise MergeError(f"merge rejected: {null_keys} rows have a null CIK")
        duplicates = find_duplicate_keys(con, str_paths, "cik")
        if duplicates:
            raise MergeError(
                f"merge rejected: duplicate CIK rows across chunks: {duplicates}"
            )
        report.duplicate_accessions = find_duplicate_accessions(con, str_paths)
        if report.duplicate_accessions:
            report.warnings.append(
                f"{len(report.duplicate_accessions)} duplicate accession(s) observed; "
                "accession is not globally unique"
            )
    finally:
        con.close()

    emit({"type": "merge_stage", "stage": "publishing_parts"})
    part_paths = _publish_chunk_parts(report, run_paths.metadata, chunk_paths)

    row_count = sum(int(part["row_count"]) for part in report.parts)
    if row_count != plan.row_count:
        raise MergeError(
            f"merge rejected: published row count {row_count} != planned {plan.row_count}"
        )

    report.row_count = row_count
    report.parts_digest = parts_digest(report.parts)
    report.filing_record_count = _filing_record_count(
        [str(path) for path in part_paths]
    )
    emit({"type": "cik_index", "stage": "publishing"})
    publish_cik_index(report, run_paths.metadata, _published_ciks(part_paths))
    emit({"type": "readback_done", "rows": row_count})
    return report


def publish_snapshot(
    report: MergeReport, metadata_paths: MetadataPaths
) -> dict[str, Any]:
    """Write the snapshot manifest and advance the current pointer atomically.
    Manifest first, pointer last: a crash between leaves an unpublished but complete
    directory, never a pointer to an unfinished dataset.
    """
    manifest = report.to_dict()
    atomic_write_json(
        metadata_paths.snapshot_manifest(report.snapshot_id),
        manifest,
        canonical=False,
        indent=2,
    )
    parent_refs: list[ParentRef] = []
    catalog = DAGCatalog(metadata_paths.snapshots_root)
    if report.parent_snapshot_id:
        parent_sha = catalog.get_manifest_sha256(report.parent_snapshot_id) or ""
        parent_refs.append(
            ParentRef(
                snapshot_id=report.parent_snapshot_id,
                manifest_sha256=parent_sha,
            )
        )
    part_descriptors = tuple(
        PartDescriptor(
            path=str(p["path"]),
            sha256=str(p["sha256"]),
            row_count=int(p["row_count"]),
            byte_size=int(p.get("byte_count", 0)),
        )
        for p in report.parts
    )
    dag_manifest = DAGNodeManifest(
        snapshot_id=report.snapshot_id,
        kind="delta" if report.parent_snapshot_id else "checkpoint",
        parents=tuple(parent_refs),
        checkpoint_anchor_id=(
            report.snapshot_id
            if not report.parent_snapshot_id
            else report.parent_snapshot_id
        ),
        lineage_depth=1 if report.parent_snapshot_id else 0,
        created_at=report.merged_at or utc_now_iso(),
        relations={"submissions": part_descriptors},
        logical_fingerprint=report.parts_digest or "",
    )
    catalog.publish_node(dag_manifest)
    return manifest


def publish_current_snapshot(metadata_paths: MetadataPaths, snapshot_id: str) -> Path:
    """Point ``current`` at an already-published snapshot.
    A pointer move and nothing else, validated first: a pointer to a nonexistent
    dataset is worse than a stale one.
    """
    manifest_path = metadata_paths.snapshot_manifest(snapshot_id)
    catalog = DAGCatalog(metadata_paths.snapshots_root)
    if not catalog.has_snapshot(snapshot_id) and not manifest_path.is_file():
        raise MergeError(
            f"cannot point current at {snapshot_id!r}: snapshot is missing"
        )
    catalog.write_pointer("main", snapshot_id)
    return catalog.catalog_file
