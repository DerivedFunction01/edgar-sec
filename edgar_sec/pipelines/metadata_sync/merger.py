"""Coordinator merge: validate every chunk, then publish one sorted snapshot.

The coordinator is the only component that writes published artifacts. Two
classes of finding are deliberately distinguished:

* Failures - duplicate or null CIKs, schema drift, plan coverage gaps,
  mismatched row counts, and foreign chunk files.
* Reportable fan-out - duplicate accessions. The same filing is legitimately
  listed by more than one registrant, so duplicates are surfaced as a warning
  and never reject a merge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from edgar_sec.domain.submissions.schemas import SCHEMA_VERSION
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.infra.storage.duckdb import (
    concat_to_parquet,
    connect,
    find_duplicate_keys,
    find_duplicate_nested_values,
    find_null_keys,
)
from edgar_sec.infra.storage.parquet import count_parquet_rows, read_parquet_schema

from .paths import MetadataPaths, RunPaths
from .planner import utc_now_iso

__all__ = ["MergeError", "MergeReport", "merge_chunks", "publish_snapshot"]


class MergeError(RuntimeError):
    """Merge rejected; the snapshot was not published."""


@dataclass(slots=True)
class MergeReport:
    """Result of one merge attempt."""

    snapshot_id: str
    output_path: str = ""
    row_count: int = 0
    chunk_count: int = 0
    filing_record_count: int = 0
    artifact_sha256: str = ""
    plan_id: str = ""
    input_fingerprint: str = ""
    schema_version: str = SCHEMA_VERSION
    merged_at: str = ""
    duplicate_accessions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serializable report for the snapshot manifest."""
        return {
            "snapshot_id": self.snapshot_id,
            "output_path": self.output_path,
            "row_count": self.row_count,
            "chunk_count": self.chunk_count,
            "filing_record_count": self.filing_record_count,
            "artifact_sha256": self.artifact_sha256,
            "plan_id": self.plan_id,
            "input_fingerprint": self.input_fingerprint,
            "schema_version": self.schema_version,
            "merged_at": self.merged_at,
            "duplicate_accessions": self.duplicate_accessions,
            "warnings": self.warnings,
        }


def _filing_record_count(paths: list[str]) -> int:
    import pyarrow.parquet as pq

    total = 0
    for path in paths:
        table = pq.read_table(path, columns=["filings"])
        total += sum(
            len(value) for value in table.column("filings").to_pylist() if value
        )
    return total


def validate_chunks(plan: dict, run_paths: RunPaths) -> list[Path]:
    """Validate every planned chunk and return the ordered checkpoint paths."""
    planned = {
        int(chunk["chunk_id"]): tuple(chunk["cik_padded"]) for chunk in plan["chunks"]
    }
    expected_rows = int(plan["row_count"])
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

    fingerprint = str(plan.get("input_fingerprint", ""))
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


def merge_chunks(
    plan: dict,
    run_paths: RunPaths,
    snapshot_id: str,
) -> MergeReport:
    """Validate all chunks and publish a sorted snapshot dataset."""
    chunk_paths = validate_chunks(plan, run_paths)
    str_paths = [str(path) for path in chunk_paths]
    report = MergeReport(
        snapshot_id=snapshot_id,
        chunk_count=len(chunk_paths),
        plan_id=str(plan.get("plan_id", "")),
        input_fingerprint=str(plan.get("input_fingerprint", "")),
        merged_at=utc_now_iso(),
    )

    output_path = run_paths.metadata.snapshot_file(snapshot_id)
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
        row_count = concat_to_parquet(con, str_paths, output_path, order_by=("cik",))
    finally:
        con.close()

    if row_count != int(plan["row_count"]):
        raise MergeError(
            f"merge rejected: merged row count {row_count} "
            f"!= planned {plan['row_count']}"
        )

    if not read_parquet_schema(output_path).equals(plan_schema(), check_metadata=False):
        raise MergeError("merge rejected: published artifact schema drifted")

    report.row_count = row_count
    report.output_path = str(output_path)
    report.artifact_sha256 = file_sha256(output_path)
    report.filing_record_count = _filing_record_count([str(output_path)])
    return report


def publish_snapshot(
    report: MergeReport, metadata_paths: MetadataPaths
) -> dict[str, Any]:
    """Write the snapshot manifest and advance the current pointer atomically."""
    manifest = report.to_dict()
    atomic_write_json(
        metadata_paths.snapshot_manifest(report.snapshot_id),
        manifest,
        canonical=False,
        indent=2,
    )
    atomic_write_json(
        metadata_paths.current_pointer,
        {
            "snapshot_id": report.snapshot_id,
            "plan_id": report.plan_id,
            "row_count": report.row_count,
            "artifact_sha256": report.artifact_sha256,
            "updated_at": report.merged_at,
        },
        canonical=False,
        indent=2,
    )
    return manifest
