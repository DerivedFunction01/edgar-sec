"""Phase-owned validation and publication of completed metadata chunks."""

from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import dataclass, field

from .schemas import SCHEMA_VERSION, TERMINAL_STATUSES
from .storage import make_phase_store


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
            key: getattr(self, key)
            for key in (
                "artifacts_dir",
                "schema_version",
                "input_fingerprint",
                "chunk_count",
                "row_count",
                "filing_record_count",
                "excluded_chunks",
                "errors",
                "warnings",
                "output_path",
                "duplicate_accessions",
            )
        }


def _plan(artifacts_dir: str) -> dict:
    path = os.path.join(artifacts_dir, "plan.json")
    if not os.path.exists(path):
        raise MergeError(f"missing plan.json in {artifacts_dir}")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def merge_chunks(
    artifacts_dir: str,
    output_path: str,
    *,
    allow_accession_duplicates: bool = False,
    storage_format: str | None = None,
    output_storage_format: str | None = None,
    plan: dict | None = None,
    partition_id: int | None = None,
) -> MergeReport:
    if plan is None:
        plan = _plan(artifacts_dir)
    expected_fingerprint = plan.get("input_fingerprint", "")
    expected_version = plan.get("schema_version", SCHEMA_VERSION)
    source_format = storage_format or plan.get("storage_format", "parquet")
    target_format = output_storage_format or (
        "jsonl" if output_path.endswith(".jsonl") else "parquet"
    )
    if source_format not in {"parquet", "jsonl"} or target_format not in {
        "parquet",
        "jsonl",
    }:
        raise MergeError("unsupported storage format")
    partition = None
    if partition_id is not None:
        partition = next((item for item in plan.get("partitions", []) if item["partition_id"] == partition_id), None)
        if partition is None:
            raise MergeError(f"partition {partition_id} is not present in plan.json")
    assigned = {chunk["chunk_id"]: chunk for chunk in (partition or plan).get("chunks", [])}
    if not assigned:
        raise MergeError("plan contains no chunks")
    source_root = artifacts_dir if partition is None else os.path.join(artifacts_dir, "partitions", f"partition-{partition_id:05d}")
    source = make_phase_store(source_format, source_root, "merge", expected_fingerprint)
    found = {ref.chunk_id: ref for ref in source.list()}
    report = MergeReport(
        artifacts_dir, expected_version, expected_fingerprint, len(assigned), 0, 0
    )
    rows: list[dict] = []
    seen_ranges = []
    for chunk_id in sorted(assigned):
        chunk = assigned[chunk_id]
        ref = found.get(chunk_id)
        if ref is None:
            report.excluded_chunks.append(
                {"chunk_id": chunk_id, "reason": "missing checkpoint"}
            )
            continue
        if (
            ref.version != expected_version
            or ref.start_row != chunk["start_row"]
            or ref.end_row != chunk["end_row"]
        ):
            report.excluded_chunks.append(
                {
                    "chunk_id": chunk_id,
                    "reason": "checkpoint metadata differs from plan",
                }
            )
            continue
        chunk_rows = source.load(chunk_id)
        expected_rows = chunk["end_row"] - chunk["start_row"] + 1
        if len(chunk_rows) != expected_rows:
            report.excluded_chunks.append(
                {
                    "chunk_id": chunk_id,
                    "reason": f"row count {len(chunk_rows)} != expected {expected_rows}",
                }
            )
            continue
        seen_ranges.append((chunk_id, chunk["start_row"], chunk["end_row"]))
        rows.extend(chunk_rows)
    if set(found) - set(assigned):
        raise MergeError(
            f"merge rejected: chunk files outside the plan: {sorted(set(found) - set(assigned))}"
        )
    if report.excluded_chunks:
        raise MergeError(
            "merge rejected: incomplete or invalid chunks: "
            + json.dumps(report.excluded_chunks)
        )
    expected_row_count = (partition or plan).get("row_count", -1)
    ordered_ranges = sorted(seen_ranges, key=lambda item: item[1])
    next_row = 0
    for _, start, end in ordered_ranges:
        if start != next_row:
            raise MergeError(
                "merge rejected: chunks have overlapping or missing row ranges"
            )
        next_row = end + 1
    if next_row != expected_row_count:
        raise MergeError("merge rejected: chunks do not cover the planned row count")
    ciks = [row["cik"] for row in rows]
    if len(set(ciks)) != len(ciks):
        dupes = [cik for cik, count in Counter(ciks).items() if count > 1]
        raise MergeError(f"merge rejected: duplicate CIK rows: {dupes[:10]}")
    if sorted(ciks) != sorted((partition or plan).get("cik_padded", [])):
        raise MergeError("merge rejected: CIK coverage does not match the plan")
    versions = {row.get("schema_version") for row in rows}
    if versions != {expected_version}:
        raise MergeError(f"merge rejected: mixed schema versions {sorted(versions)}")
    fingerprints = {row.get("input_fingerprint") for row in rows}
    if fingerprints != {expected_fingerprint}:
        raise MergeError("merge rejected: row input fingerprints do not match the plan")
    non_terminal = [
        row["status"] for row in rows if row["status"] not in TERMINAL_STATUSES
    ]
    if non_terminal:
        raise MergeError(f"merge rejected: {len(non_terminal)} rows are not terminal")
    seen = set()
    duplicates = []
    for row in rows:
        for filing in row.get("filings") or []:
            key = filing.get("accession_number_normalized")
            if key and key in seen and key not in duplicates:
                duplicates.append(key)
            if key:
                seen.add(key)
    report.duplicate_accessions = duplicates
    if duplicates and not allow_accession_duplicates:
        raise MergeError(
            f"merge rejected: {len(duplicates)} duplicate accession(s); re-run with allow_accession_duplicates to override"
        )
    if duplicates:
        report.warnings.append(f"{len(duplicates)} duplicate accession(s) permitted")
    report.row_count = len(rows)
    report.filing_record_count = sum(len(row.get("filings") or []) for row in rows)
    if target_format == source_format:
        # Validation above is phase-owned; physical same-format assembly is
        # delegated to the chunk backend so it can stream and publish atomically.
        source.finalize_chunks(output_path)
    else:
        target = make_phase_store(
            target_format,
            os.path.dirname(os.path.abspath(output_path)),
            "merge",
            expected_fingerprint,
        )
        target.finalize(rows, output_path)
    report.output_path = os.path.abspath(output_path)
    report_path = os.path.join(artifacts_dir, "merge", "merge_report.json")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report.to_dict(), fh, indent=2, sort_keys=True)
    return report
