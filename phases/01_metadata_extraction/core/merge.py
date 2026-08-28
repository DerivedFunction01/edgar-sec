"""Phase-owned validation and publication of completed metadata chunks."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field

from defs.runtime.paths import (
    merge_report_path_in,
    partition_artifact_path_in,
    partition_merge_report_path_in,
)
from defs.storage import (
    MergeValidationSpec,
    concat_to_parquet,
    connect,
    count_nested_values,
    count_rows,
    duplicate_values,
    ordered_keys,
    validate_files,
)

from .schemas import (
    SCHEMA_VERSION,
    SUBMISSION_METADATA_SCHEMA,
    TERMINAL_STATUSES,
)
from .storage import make_phase_store

logger = logging.getLogger("metadata.merge")


class MergeError(Exception):
    pass


def _emit(progress: Callable[[dict], None] | None, event: dict) -> None:
    if progress is None:
        return
    try:
        progress(event)
    except Exception:
        logger.exception("merge progress callback failed")


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
    partition_id: int | None = None
    plan_hash: str = ""
    report_source: str = "chunk_checkpoints"

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
                "partition_id",
                "plan_hash",
                "report_source",
            )
        }


def _plan(artifacts_dir: str) -> dict:
    path = os.path.join(artifacts_dir, "plan.json")
    if not os.path.exists(path):
        raise MergeError(f"missing plan.json in {artifacts_dir}")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _merge_spec(plan: dict) -> MergeValidationSpec:
    return MergeValidationSpec(
        schema=SUBMISSION_METADATA_SCHEMA,
        key_field="cik",
        schema_version=plan.get("schema_version", SCHEMA_VERSION),
        fingerprint=plan.get("input_fingerprint", ""),
        terminal_statuses=tuple(sorted(TERMINAL_STATUSES)),
        uniqueness_paths=(("filings", "accession_number_normalized"),),
        order_by=("cik",),
    )


def _raise_validation_failure(
    validation, *, scope: str, expected_rows: int | None = None
) -> None:
    if expected_rows is not None and validation.row_count != expected_rows:
        raise MergeError(
            f"merge rejected: {scope} row count {validation.row_count} "
            f"!= expected {expected_rows}"
        )
    if validation.invalid_field_rows:
        raise MergeError(
            f"merge rejected: {scope} contains {validation.invalid_field_rows} "
            "rows with invalid schema, fingerprint, or status"
        )
    if validation.duplicate_keys:
        raise MergeError(
            f"merge rejected: duplicate CIK rows in {scope}: "
            f"{list(validation.duplicate_keys)}"
        )


def _partition_report_payload(
    artifacts_dir: str,
    partition: dict,
    *,
    row_count: int,
    filing_record_count: int,
    duplicate_accessions: list[str],
    storage_format: str,
    schema_version: str,
    input_fingerprint: str,
    plan_hash: str,
) -> dict:
    """Rebuild a partition report from its finalized dataset artifact.

    This deliberately does not inspect chunks or trust an existing JSON
    report; the finalized artifact is the portable source of truth for
    downstream consumers and report regeneration.
    """
    report = MergeReport(
        artifacts_dir=artifacts_dir,
        schema_version=schema_version,
        input_fingerprint=input_fingerprint,
        chunk_count=len(partition.get("chunks", [])),
        row_count=row_count,
        filing_record_count=filing_record_count,
        duplicate_accessions=duplicate_accessions,
        partition_id=partition["partition_id"],
        plan_hash=plan_hash,
        output_path=os.path.abspath(
            _partition_artifact_path(
                artifacts_dir, partition["partition_id"], storage_format
            )
        ),
        report_source="finalized_partition_artifact",
    )
    _add_duplicate_warning(report)
    return report.to_dict()


def _merge_chunks(
    artifacts_dir: str,
    output_path: str,
    *,
    partition_id: int,
    storage_format: str | None = None,
    plan: dict | None = None,
    progress: Callable[[dict], None] | None = None,
) -> MergeReport:
    """Validate one partition's chunk checkpoints and publish its artifact.

    This is the only operation permitted to read chunk directories, and it is
    reachable only through :func:`merge_partition`.
    """
    if plan is None:
        plan = _plan(artifacts_dir)
    expected_fingerprint = plan.get("input_fingerprint", "")
    expected_version = plan.get("schema_version", SCHEMA_VERSION)
    source_format = storage_format or plan.get("storage_format", "parquet")
    if source_format not in {"parquet", "jsonl"}:
        raise MergeError("unsupported storage format")
    partition = next(
        (
            item
            for item in plan.get("partitions", [])
            if item["partition_id"] == partition_id
        ),
        None,
    )
    if partition is None:
        raise MergeError(f"partition {partition_id} is not present in plan.json")
    assigned = {chunk["chunk_id"]: chunk for chunk in partition.get("chunks", [])}
    if not assigned:
        raise MergeError(f"partition {partition_id} contains no chunks")
    source_root = os.path.join(
        artifacts_dir, "partitions", f"partition-{partition_id:05d}"
    )
    source = make_phase_store(source_format, source_root, "merge", expected_fingerprint)
    found = {ref.chunk_id: ref for ref in source.list()}
    report = MergeReport(
        artifacts_dir,
        expected_version,
        expected_fingerprint,
        len(assigned),
        0,
        0,
        partition_id=partition_id,
        plan_hash=plan.get("plan_hash", ""),
        report_source="chunk_checkpoints",
    )
    for chunk_id, chunk in sorted(assigned.items()):
        ref = found.get(chunk_id)
        if ref is None:
            report.excluded_chunks.append(
                {"chunk_id": chunk_id, "reason": "missing checkpoint"}
            )
        elif (
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
    if set(found) - set(assigned):
        raise MergeError(
            f"merge rejected: chunk files outside the plan: {sorted(set(found) - set(assigned))}"
        )
    if report.excluded_chunks:
        raise MergeError(
            "merge rejected: incomplete or invalid chunks: "
            + json.dumps(report.excluded_chunks)
        )
    expected_row_count = partition.get("row_count", -1)
    ordered_ranges = sorted(
        (
            chunk["chunk_id"],
            chunk["start_row"],
            chunk["end_row"],
        )
        for chunk in assigned.values()
    )
    next_row = 0
    for _, start, end in ordered_ranges:
        if start != next_row:
            raise MergeError(
                "merge rejected: chunks have overlapping or missing row ranges"
            )
        next_row = end + 1
    if next_row != expected_row_count:
        raise MergeError("merge rejected: chunks do not cover the planned row count")
    spec = _merge_spec(plan)
    files = [found[chunk_id].path for chunk_id in sorted(assigned)]
    try:
        with connect() as con:
            validation = validate_files(con, source_format, files, spec)
            _raise_validation_failure(
                validation,
                scope=f"partition {partition_id}",
                expected_rows=expected_row_count,
            )
            keys = ordered_keys(con, source_format, files, spec)
            if sorted(keys) != sorted(partition.get("cik_padded", [])):
                raise MergeError("merge rejected: CIK coverage does not match the plan")
            report.duplicate_accessions = duplicate_values(
                con,
                source_format,
                files,
                spec.schema,
                ("filings", "accession_number_normalized"),
            )
            report.filing_record_count = count_nested_values(
                con,
                source_format,
                files,
                spec.schema,
                ("filings", "accession_number_normalized"),
            )
            _emit(
                progress,
                {
                    "type": "merge_stage",
                    "stage": "validate",
                    "rows": validation.row_count,
                },
            )
            concat_to_parquet(con, source_format, files, spec, output_path)
            _emit(
                progress,
                {
                    "type": "merge_stage",
                    "stage": "publish",
                    "rows": validation.row_count,
                },
            )
            report.row_count = validation.row_count
            finalized_count = count_rows(con, output_path)
    except MergeError:
        raise
    except Exception as exc:
        raise MergeError(f"merge rejected: {exc}") from exc
    if finalized_count != report.row_count:
        raise MergeError("finalized artifact row count differs from validated chunks")
    _emit(progress, {"type": "readback_done", "rows": finalized_count})
    logger.info(
        "partition %d: artifact validated (rows=%d) -> %s",
        partition_id,
        finalized_count,
        output_path,
    )
    report.row_count = finalized_count
    _add_duplicate_warning(report)
    report.report_source = "finalized_partition_artifact"
    report.output_path = os.path.abspath(output_path)
    report_path = partition_merge_report_path_in(artifacts_dir, partition_id)
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report.to_dict(), fh, indent=2, sort_keys=True)
    return report


def _partition_artifact_path(
    artifacts_dir: str, partition_id: int, storage_format: str
):
    return partition_artifact_path_in(
        artifacts_dir,
        partition_id,
        f"submission_metadata.{storage_format}",
    )


def merge_partition(
    artifacts_dir: str,
    partition_id: int,
    *,
    output_path: str | None = None,
    storage_format: str | None = None,
    output_storage_format: str | None = None,
    progress: Callable[[dict], None] | None = None,
) -> MergeReport:
    """Validate one partition's chunks and publish its portable artifact."""
    plan = _plan(artifacts_dir)
    source_format = storage_format or plan.get("storage_format", "parquet")
    if output_storage_format == "jsonl" or (
        output_path and output_path.endswith(".jsonl")
    ):
        raise MergeError("DuckDB merge publishes Parquet artifacts only")
    output = output_path or str(
        _partition_artifact_path(artifacts_dir, partition_id, "parquet")
    )
    return _merge_chunks(
        artifacts_dir,
        output,
        storage_format=source_format,
        plan=plan,
        partition_id=partition_id,
        progress=progress,
    )


def merge_partition_artifacts(
    artifacts_dir: str,
    output_path: str,
    *,
    storage_format: str | None = None,
    output_storage_format: str | None = None,
    progress: Callable[[dict], None] | None = None,
) -> MergeReport:
    """Validate and combine complete partition artifacts only."""
    if output_storage_format == "jsonl" or output_path.endswith(".jsonl"):
        raise MergeError("DuckDB merge publishes Parquet artifacts only")
    plan = _plan(artifacts_dir)
    partitions = plan.get("partitions", [])
    if not partitions:
        raise MergeError(
            "merge requires a partitioned plan and finalized partition artifacts"
        )
    # Partition artifacts are always published as Parquet regardless of the
    # chunk/checkpoint format, so the final merge reads Parquet only. The
    # checkpoint storage_format is accepted for CLI compatibility but does
    # not affect artifact reading.
    artifact_format = "parquet"
    expected_version = plan.get("schema_version", SCHEMA_VERSION)
    expected_fingerprint = plan.get("input_fingerprint", "")
    plan_hash = plan.get("plan_hash", "")
    report = MergeReport(
        artifacts_dir,
        expected_version,
        expected_fingerprint,
        len(partitions),
        0,
        0,
        plan_hash=plan_hash,
        report_source="finalized_partition_artifacts",
    )
    combined_files: list[str] = []
    ordered_partitions = sorted(partitions, key=lambda item: item["partition_id"])
    spec = _merge_spec(plan)
    with connect() as con:
        for partition in ordered_partitions:
            partition_id = partition["partition_id"]
            path = _partition_artifact_path(artifacts_dir, partition_id, "parquet")
            if not path.exists():
                raise MergeError(
                    f"missing partition artifact for partition {partition_id}: {path}"
                )
            validation = validate_files(con, artifact_format, [str(path)], spec)
            _raise_validation_failure(
                validation,
                scope=f"partition {partition_id}",
                expected_rows=partition.get("row_count"),
            )
            keys = ordered_keys(con, artifact_format, str(path), spec)
            if keys != partition.get("cik_padded", []):
                raise MergeError(
                    f"partition {partition_id} CIK coverage differs from plan"
                )
            duplicate_accessions = duplicate_values(
                con,
                artifact_format,
                [str(path)],
                spec.schema,
                ("filings", "accession_number_normalized"),
            )
            # Reports are regenerated from the finalized artifact, never from
            # chunks and never trusted from an earlier run.
            payload = _partition_report_payload(
                artifacts_dir,
                partition,
                row_count=validation.row_count,
                filing_record_count=count_nested_values(
                    con,
                    artifact_format,
                    [str(path)],
                    spec.schema,
                    ("filings", "accession_number_normalized"),
                ),
                duplicate_accessions=duplicate_accessions,
                storage_format="parquet",
                schema_version=expected_version,
                input_fingerprint=expected_fingerprint,
                plan_hash=plan_hash,
            )
            report_path = partition_merge_report_path_in(artifacts_dir, partition_id)
            os.makedirs(os.path.dirname(report_path), exist_ok=True)
            with open(report_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, sort_keys=True)
            _emit(
                progress,
                {
                    "type": "partition_validated",
                    "partition_id": partition_id,
                    "rows": validation.row_count,
                },
            )
            logger.info(
                "final merge: partition %d/%d validated (rows=%d)",
                len(combined_files) + 1,
                len(ordered_partitions),
                validation.row_count,
            )
            combined_files.append(str(path))
        global_validation = validate_files(con, artifact_format, combined_files, spec)
        if global_validation.distinct_keys != plan.get("row_count"):
            raise MergeError("merged partition artifacts do not cover the planned CIKs")
        report.duplicate_accessions = duplicate_values(
            con,
            artifact_format,
            combined_files,
            spec.schema,
            ("filings", "accession_number_normalized"),
        )
        report.row_count = global_validation.row_count
        report.filing_record_count = count_nested_values(
            con,
            artifact_format,
            combined_files,
            spec.schema,
            ("filings", "accession_number_normalized"),
        )
        _emit(
            progress,
            {"type": "merge_stage", "stage": "validate", "rows": report.row_count},
        )
        concat_to_parquet(con, artifact_format, combined_files, spec, output_path)
        _emit(
            progress,
            {"type": "merge_stage", "stage": "publish", "rows": report.row_count},
        )
        finalized_count = count_rows(con, output_path)
    if finalized_count != report.row_count:
        raise MergeError(
            "finalized artifact row count differs from partition artifacts"
        )
    _emit(progress, {"type": "readback_done", "rows": finalized_count})
    logger.info(
        "final merge: artifact validated (rows=%d) -> %s", finalized_count, output_path
    )
    _add_duplicate_warning(report)
    report.report_source = "finalized_artifact"
    report.output_path = os.path.abspath(output_path)
    report_path = merge_report_path_in(artifacts_dir)
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report.to_dict(), fh, indent=2, sort_keys=True)
    return report


def _add_duplicate_warning(report: MergeReport) -> None:
    if report.duplicate_accessions:
        report.warnings.append(
            f"{len(report.duplicate_accessions)} duplicate accession(s) observed; "
            "accession is not globally unique"
        )
