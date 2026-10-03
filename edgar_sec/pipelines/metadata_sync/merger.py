"""Coordinator merge: validate every chunk, then publish one sorted snapshot.

The coordinator is the only component that writes published artifacts. Two
classes of finding are deliberately distinguished:

* Failures - duplicate or null CIKs, schema drift, plan coverage gaps,
  mismatched row counts, and foreign chunk files.
* Reportable fan-out - duplicate accessions. The same filing is legitimately
  listed by more than one registrant, so duplicates are surfaced as a warning
  and never reject a merge.

Publication is multipart: :func:`publish_parts` writes an ordered list of Parquet
parts and records them in the manifest, leaving the singular ``output_path`` /
``artifact_sha256`` pair empty on purpose so a reader that understands only the
legacy single-file shape fails loudly instead of ingesting one part of the
dataset. A sorted distinct CIK index is written beside the parts for Phase 1's
own membership, coverage, and augmentation operations, and recorded in the
manifest. Phase 2 does not open it.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from edgar_sec.domain.submissions.schemas import SCHEMA_VERSION
from edgar_sec.foundation.hashing import file_sha256, sha256_bytes
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.infra.storage.duckdb import (
    connect,
    find_duplicate_keys,
    find_duplicate_nested_values,
    find_null_keys,
)
from edgar_sec.infra.storage.parquet import count_parquet_rows, read_parquet_schema

from .paths import PARTS_DIR_NAME, MetadataPaths, RunPaths
from .planner import Plan, utc_now_iso
from .roster import read_cik_index, write_cik_index
from .snapshot import SNAPSHOT_MANIFEST_VERSION

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
    registry_id: str = ""
    source_snapshot_id: str = ""
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

        A published snapshot is described by its ordered ``parts`` list. The
        singular ``output_path``/``artifact_sha256`` pair is left empty for a
        multipart snapshot on purpose: pointing them at the first part would let
        a reader that understands only the legacy shape silently ingest a
        fraction of the dataset. A reader must either honour the part list or fail
        loudly on the empty payload.
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
            "registry_id": self.registry_id,
            "source_snapshot_id": self.source_snapshot_id,
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

    The index is built from what is on disk rather than from the roster, so a
    snapshot whose parts do not carry the planned cohort is visible in the index
    instead of surfacing as a surprise in a later consumer.
    """
    import pyarrow.parquet as pq

    ciks: list[str] = []
    for path in part_paths:
        table = pq.read_table(path, columns=["cik"])
        ciks.extend(str(value) for value in table.column("cik").to_pylist())
    return ciks


def parts_digest(parts: list[dict[str, Any]]) -> str:
    """One digest over the ordered part digests.

    A snapshot is identified by the ordered set of files that carry it, so a
    single value can bind a pointer or a downstream manifest to the exact dataset
    without rehashing every part at discovery time.
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
    planned = {chunk_id: plan.chunk_ciks(chunk_id) for chunk_id in plan.chunk_ids()}
    expected_rows = int(plan.row_count)
    if sum(len(ciks) for ciks in planned.values()) != expected_rows:
        raise MergeError("plan chunks do not cover the planned CIK count")

    found: dict[int, Path] = {}
    for path in sorted(run_paths.chunk_dir.glob("chunk_*.parquet")):
        try:
            chunk_id = int(path.stem.split("_", 1)[1])
        except (IndexError, ValueError):
            continue
        found[chunk_id] = path

    foreign = set(found) - set(planned)
    if foreign:
        raise MergeError(
            f"merge rejected: chunk files outside the plan: {sorted(foreign)}"
        )
    missing = sorted(set(planned) - set(found))
    if missing:
        raise MergeError(f"merge rejected: missing chunk checkpoints: {missing}")

    fingerprint = plan.input_fingerprint
    for chunk_id in sorted(planned):
        path = found[chunk_id]
        if not read_parquet_schema(path).equals(plan_schema(), check_metadata=False):
            raise MergeError(
                f"merge rejected: chunk {chunk_id} schema drifted from the dataset contract"
            )
        rows = count_parquet_rows(path)
        if rows != len(planned[chunk_id]):
            raise MergeError(
                f"merge rejected: chunk {chunk_id} row count {rows} "
                f"!= planned {len(planned[chunk_id])}"
            )

    import pyarrow.parquet as pq

    for chunk_id in sorted(planned):
        table = pq.read_table(
            found[chunk_id], columns=["cik", "input_fingerprint", "status"]
        )
        ciks = tuple(str(v) for v in table.column("cik").to_pylist())
        if set(ciks) != set(planned[chunk_id]) or len(ciks) != len(planned[chunk_id]):
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

    The index is derived from the published rows rather than from the plan, so it
    is a statement about the artifact on disk and not about what was requested.
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
    """Publish validated source files as a snapshot's ordered Parquet parts.

    Parts are byte copies of already-validated files, not a re-materialization.
    Copying performs the same validation work at a fraction of the I/O a
    decompress-sort-recompress pass would, and it makes the published dataset
    exactly the set of files the merge accepted. A full merge passes its chunk
    files; an augmentation passes the base snapshot's parts followed by its delta
    chunks.

    Each source label is recorded on its part, so a consumer can tell which
    chunk or which base part a row came from without inspecting the file.

    The trade is row order. A snapshot is in part order and each part is in the
    order its source file held, so the dataset is *not* globally sorted by CIK.
    That is recorded in the manifest as ``sort_order`` so a consumer cannot
    mistake one for the other, and ``ciks.parquet`` remains the sorted membership
    index for lookups by CIK.
    """
    parts_dir = metadata_paths.snapshot_parts_dir(report.snapshot_id)
    parts_dir.mkdir(parents=True, exist_ok=True)
    published: list[Path] = []
    for index, (label, source) in enumerate(sources):
        name = f"part-{index:05d}.parquet"
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

    ``progress`` receives one event per merge stage. A merge over millions of
    rows is long enough that silence is indistinguishable from a hang, so the
    stages are reported. A failing progress callback never aborts publication:
    presentation must not be able to reject a validated snapshot.

    ``lineage`` carries the parent, roster, and source identities an augmented
    artifact must record. It is optional because a full ingest has no parent, and
    a full ingest must not invent one.

    A delta plan is refused. This function publishes exactly the chunks the plan
    produced, and a delta plan's chunks hold only the CIKs missing from its base,
    so merging one would publish a dataset that drops every base row while
    recording that base as its parent. Recombining base and delta is
    :mod:`augmentation`'s job, which passes the base parts in as merge inputs;
    doing it here would mean silently guessing which snapshot to resurrect.
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
        registry_id=recorded.get("registry_id", ""),
        source_snapshot_id=recorded.get("source_snapshot_id", ""),
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
        report.duplicate_accessions = find_duplicate_nested_values(
            con, str_paths, "filings", "accession_number"
        )
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

    The manifest is the snapshot's commit record and is written first; the
    pointer is written last. A crash between the two leaves an unpublished but
    complete snapshot directory, which the next merge overwrites, rather than a
    pointer naming a dataset that was never finished.
    """
    manifest = report.to_dict()
    atomic_write_json(
        metadata_paths.snapshot_manifest(report.snapshot_id),
        manifest,
        canonical=False,
        indent=2,
    )
    pointer: dict[str, Any] = {
        "snapshot_id": report.snapshot_id,
        "plan_id": report.plan_id,
        "row_count": report.row_count,
        "updated_at": report.merged_at,
    }
    if report.parts:
        pointer["part_count"] = len(report.parts)
        pointer["parts_digest"] = report.parts_digest
        pointer["snapshot_manifest"] = metadata_paths.snapshot_manifest(
            report.snapshot_id
        ).name
    else:
        pointer["artifact_sha256"] = report.artifact_sha256
    atomic_write_json(
        metadata_paths.current_pointer, pointer, canonical=False, indent=2
    )
    return manifest


def publish_current_snapshot(metadata_paths: MetadataPaths, snapshot_id: str) -> Path:
    """Point ``current`` at an already-published snapshot.

    ``publish_snapshot`` advances the pointer as a side effect of a merge, which
    means the pointer can only ever move forward. This is the explicit operation
    that moves it back, so a reader can be sent to an earlier snapshot that is
    still on disk and still valid.

    It is deliberately a pointer move and nothing else: no snapshot is written,
    removed, or rewritten. Selecting an older snapshot does not unpublish a newer
    one, and the next successful merge advances the pointer again.

    The target is validated first. Pointing at a snapshot whose manifest is
    absent or names a different id would send a reader to a dataset that does not
    exist, which is strictly worse than leaving a stale pointer in place.
    """
    manifest_path = metadata_paths.snapshot_manifest(snapshot_id)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MergeError(
            f"cannot point current at {snapshot_id!r}: {manifest_path} is unreadable "
            f"({exc})"
        ) from exc
    if (
        not isinstance(manifest, dict)
        or str(manifest.get("snapshot_id", "")) != snapshot_id
    ):
        raise MergeError(
            f"cannot point current at {snapshot_id!r}: {manifest_path} does not "
            "describe that snapshot"
        )

    pointer: dict[str, Any] = {
        "snapshot_id": snapshot_id,
        "plan_id": str(manifest.get("plan_id", "")),
        "row_count": int(manifest.get("row_count", 0) or 0),
        "updated_at": str(manifest.get("merged_at", "")),
    }
    if manifest.get("parts"):
        pointer["part_count"] = len(manifest["parts"])
        pointer["parts_digest"] = str(manifest.get("parts_digest", ""))
        pointer["snapshot_manifest"] = manifest_path.name
    else:
        pointer["artifact_sha256"] = str(manifest.get("artifact_sha256", ""))
    atomic_write_json(
        metadata_paths.current_pointer, pointer, canonical=False, indent=2
    )
    return metadata_paths.current_pointer
