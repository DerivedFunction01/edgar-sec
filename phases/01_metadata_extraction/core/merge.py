"""Chunk validation and unified output merge (manual, data-driven).

Merge accepts only finalized checkpoints for the same input fingerprint and
schema version. It verifies exactly one metadata row per assigned CIK, no
duplicate nested filing accessions, no overlapping or missing chunk ranges,
and expected row counts before writing the unified Parquet dataset plus a
merge report.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import pyarrow as pa
import pyarrow.parquet as pq

from .checkpoints import list_chunk_checkpoints, load_checkpoint
from .schemas import SCHEMA_VERSION, TERMINAL_STATUSES


class MergeError(Exception):
    pass


@dataclass
class MergeReport:
    artifacts_dir: str
    schema_version: str
    input_fingerprint: str
    chunk_count: int
    row_count: int
    filing_record_count: int
    excluded_chunks: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    output_path: str = ""
    duplicate_accessions: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "artifacts_dir": self.artifacts_dir,
            "schema_version": self.schema_version,
            "input_fingerprint": self.input_fingerprint,
            "chunk_count": self.chunk_count,
            "row_count": self.row_count,
            "filing_record_count": self.filing_record_count,
            "excluded_chunks": self.excluded_chunks,
            "errors": self.errors,
            "warnings": self.warnings,
            "output_path": self.output_path,
            "duplicate_accessions": self.duplicate_accessions,
        }


def _plan(artifacts_dir: str) -> dict:
    path = os.path.join(artifacts_dir, "plan.json")
    if not os.path.exists(path):
        raise MergeError(f"missing plan.json in {artifacts_dir}")
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def merge_chunks(
    artifacts_dir: str,
    output_path: str,
    *,
    allow_accession_duplicates: bool = False,
) -> MergeReport:
    """Validate and merge completed chunk checkpoints into the unified
    ``submission_metadata`` dataset. Raises MergeError on any contract
    violation; failures never silently merge partial work."""
    plan = _plan(artifacts_dir)
    expected_fingerprint = plan.get("input_fingerprint", "")
    expected_version = plan.get("schema_version", SCHEMA_VERSION)

    assigned: dict[int, dict] = {chunk["chunk_id"]: chunk for chunk in plan.get("chunks", [])}
    if not assigned:
        raise MergeError("plan contains no chunks")

    found = {info["chunk_id"]: info for info in list_chunk_checkpoints(os.path.join(artifacts_dir, "chunks"))}
    seen_ranges: list[tuple[int, int, int]] = []
    tables: list[pa.Table] = []
    report = MergeReport(
        artifacts_dir=artifacts_dir,
        schema_version=expected_version,
        input_fingerprint=expected_fingerprint,
        chunk_count=len(assigned),
        row_count=0,
        filing_record_count=0,
    )

    for chunk_id in sorted(assigned):
        chunk = assigned[chunk_id]
        info = found.get(chunk_id)
        if info is None:
            report.excluded_chunks.append({"chunk_id": chunk_id, "reason": "missing checkpoint"})
            continue
        if info["version"] != expected_version:
            report.excluded_chunks.append(
                {"chunk_id": chunk_id, "reason": f"version {info['version']} != {expected_version}"}
            )
            continue
        if info["start_row"] != chunk["start_row"] or info["end_row"] != chunk["end_row"]:
            report.excluded_chunks.append(
                {
                    "chunk_id": chunk_id,
                    "reason": "row range differs from plan "
                    f"({info['start_row']}-{info['end_row']} vs {chunk['start_row']}-{chunk['end_row']})",
                }
            )
            continue
        seen_ranges.append((chunk_id, chunk["start_row"], chunk["end_row"]))
        try:
            table = load_checkpoint(info["path"], expected_version)
        except ValueError as exc:
            report.excluded_chunks.append({"chunk_id": chunk_id, "reason": str(exc)})
            continue
        if table is None:
            report.excluded_chunks.append({"chunk_id": chunk_id, "reason": "unreadable checkpoint"})
            continue
        expected_rows = chunk["end_row"] - chunk["start_row"] + 1
        if table.num_rows != expected_rows:
            report.excluded_chunks.append(
                {
                    "chunk_id": chunk_id,
                    "reason": f"row count {table.num_rows} != expected {expected_rows}",
                }
            )
            continue
        tables.append(table)

    # Chunk files outside the plan are unexpected artifacts, not mergeable.
    unexpected = sorted(set(found) - set(assigned))
    if unexpected:
        raise MergeError(f"merge rejected: chunk files outside the plan: {sorted(unexpected)}")

    # Complete coverage check: no missing or overlapping chunk ranges.
    covered = sum(end - start + 1 for _, start, end in seen_ranges)
    if report.excluded_chunks:
        raise MergeError(
            "merge rejected: incomplete or invalid chunks: "
            + json.dumps(report.excluded_chunks)
        )
    if covered != plan.get("row_count", -1):
        raise MergeError(f"merge rejected: chunks cover {covered} rows, plan expects {plan.get('row_count')}")

    unified = pa.concat_tables(tables) if len(tables) > 1 else tables[0]

    # Exactly one metadata row per CIK.
    ciks = unified.column("cik").to_pylist()
    if len(set(ciks)) != len(ciks):
        from collections import Counter

        dupes = [cik for cik, count in Counter(ciks).items() if count > 1]
        raise MergeError(f"merge rejected: duplicate CIK rows: {dupes[:10]}")
    plan_ciks = plan.get("cik_padded", [])
    if sorted(ciks) != sorted(plan_ciks):
        raise MergeError("merge rejected: CIK coverage does not match the plan")

    # Consistent schema/version and terminal statuses.
    versions = unified.column("schema_version").unique().to_pylist()
    if versions != [expected_version]:
        raise MergeError(f"merge rejected: mixed schema versions {versions}")
    fingerprints = unified.column("input_fingerprint").unique().to_pylist()
    if fingerprints != [expected_fingerprint]:
        raise MergeError(
            f"merge rejected: row input fingerprints {fingerprints} do not match the plan's "
            f"{expected_fingerprint}"
        )
    statuses = unified.column("status").to_pylist()
    non_terminal = [
        status for status in statuses if status not in TERMINAL_STATUSES
    ]
    if non_terminal:
        raise MergeError(f"merge rejected: {len(non_terminal)} rows are not terminal")

    # Duplicate nested filing accessions across CIK rows.
    duplicate_accessions: list[str] = []
    seen: set[str] = set()
    for filings_list in unified.column("filings"):
        for record in filings_list:
            record = record.as_py() if hasattr(record, "as_py") else record
            key = record.get("accession_number_normalized") if isinstance(record, dict) else None
            if key is None:
                continue
            if key in seen and key not in duplicate_accessions:
                duplicate_accessions.append(key)
            seen.add(key)
    report.duplicate_accessions = duplicate_accessions
    if duplicate_accessions and not allow_accession_duplicates:
        raise MergeError(
            f"merge rejected: {len(duplicate_accessions)} duplicate accession(s); "
            "re-run with allow_accession_duplicates to override"
        )
    if duplicate_accessions:
        report.warnings.append(f"{len(duplicate_accessions)} duplicate accession(s) permitted")

    report.row_count = unified.num_rows
    report.filing_record_count = sum(
        len(value or []) for value in unified.column("filings").to_pylist()
    )

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    tmp_path = output_path + ".tmp"
    pq.write_table(unified, tmp_path)
    os.replace(tmp_path, output_path)
    report.output_path = os.path.abspath(output_path)

    report_path = os.path.join(artifacts_dir, "merge", "merge_report.json")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report.to_dict(), fh, indent=2, sort_keys=True)
    return report
