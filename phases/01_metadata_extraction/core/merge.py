"""Phase-owned validation and publication of completed metadata chunks."""

from __future__ import annotations

import json
import logging
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from defs.runtime.artifacts import make_manifest, publish_manifest
from defs.runtime.paths import (
    merge_report_path_in,
    partition_artifact_path_in,
    partition_merge_report_path_in,
    resolve_paths,
)
from defs.storage import (
    MergeValidationSpec,
    concat_to_parquet,
    connect,
    count_nested_values,
    count_rows,
    duplicate_values,
    file_sha256,
    ordered_keys,
    parquet_column_names,
    validate_files,
)

from .schemas import (
    SCHEMA_VERSION,
    SUBMISSION_METADATA_SCHEMA,
    TERMINAL_STATUSES,
)
from .storage import make_phase_store

logger = logging.getLogger("metadata.merge")


def _artifact_root(artifacts_dir: str, output_path: str | None = None) -> str:
    """Find the configured artifact root without changing legacy output paths."""
    path = os.path.abspath(artifacts_dir)
    marker = f"{os.sep}metadata{os.sep}"
    if marker in path:
        return path.split(marker, 1)[0]
    if output_path is not None:
        return os.path.commonpath([path, os.path.abspath(output_path)])
    return path


def _publish_handoff(
    output_path: str,
    *,
    artifacts_dir: str,
    row_count: int,
    partition: str = "",
    upstream: tuple[str, ...] = (),
) -> None:
    root = _artifact_root(artifacts_dir, output_path)
    manifest = make_manifest(
        dataset="submission_metadata",
        phase="metadata",
        run_id=Path(artifacts_dir).name,
        schema_version=SCHEMA_VERSION,
        artifact_path=output_path,
        artifacts_root=root,
        row_count=row_count,
        partition=partition,
        upstream=upstream,
        provenance={"report_source": "finalized_artifact"},
    )
    publish_manifest(manifest, artifacts_root=root)


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
    artifact_sha256: str = ""

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
                "artifact_sha256",
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
    artifact_sha256: str = "",
) -> dict:
    """Rebuild a partition report from its finalized dataset artifact.

    This deliberately does not inspect chunks or trust an existing JSON
    report; the finalized artifact is the portable source of truth for
    downstream consumers and report regeneration. The artifact sha256 binds
    the report to the exact bytes, so the final merge can verify integrity
    without re-reading rows.
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
        artifact_sha256=artifact_sha256,
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
    report.artifact_sha256 = file_sha256(output_path)
    logger.info(
        "partition %d: artifact sha256 %s (%d rows)",
        partition_id,
        report.artifact_sha256[:12],
        finalized_count,
    )
    _add_duplicate_warning(report)
    report.report_source = "finalized_partition_artifact"
    report.output_path = os.path.abspath(output_path)
    report_path = partition_merge_report_path_in(artifacts_dir, partition_id)
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report.to_dict(), fh, indent=2, sort_keys=True)
    _publish_handoff(
        output_path,
        artifacts_dir=artifacts_dir,
        row_count=report.row_count,
        partition=f"partition-{partition_id:05d}",
    )
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


def _verify_partition_artifact(
    con,
    artifacts_dir: str,
    partition: dict,
    path,
    spec: MergeValidationSpec,
    expected_column_names: list[str],
    expected_version: str,
    expected_fingerprint: str,
    plan_hash: str,
) -> dict:
    """Verify one partition artifact and return the carried report fields.

    Cheap path (report present): the recorded sha256 binds the report to the
    exact artifact bytes, so verification is integrity + plan binding via
    metadata only — no row reads. Deep path (report missing or from an older
    format): run the full SQL validation once and regenerate the report,
    including its sha256.
    """
    partition_id = partition["partition_id"]
    report_path = partition_merge_report_path_in(artifacts_dir, partition_id)
    recorded = None
    if report_path.exists():
        with open(report_path, encoding="utf-8") as fh:
            recorded = json.load(fh)
    if isinstance(recorded, dict) and recorded.get("artifact_sha256"):
        if recorded.get("plan_hash") != plan_hash:
            raise MergeError(
                f"partition {partition_id} artifact belongs to a different plan "
                f"({recorded.get('plan_hash')!r} != {plan_hash!r})"
            )
        if recorded.get("input_fingerprint") != expected_fingerprint:
            raise MergeError(
                f"partition {partition_id} artifact fingerprint mismatch: "
                f"{recorded.get('input_fingerprint')!r} != {expected_fingerprint!r}"
            )
        if recorded.get("schema_version") != expected_version:
            raise MergeError(
                f"partition {partition_id} artifact schema version mismatch"
            )
        digest = file_sha256(str(path))
        if digest != recorded["artifact_sha256"]:
            raise MergeError(
                f"partition {partition_id} artifact content fingerprint mismatch: "
                f"sha256 {digest} != recorded {recorded['artifact_sha256']}"
            )
        rows = count_rows(con, str(path))
        if rows != recorded.get("row_count"):
            raise MergeError(
                f"partition {partition_id} artifact row count {rows} differs "
                f"from recorded {recorded.get('row_count')}"
            )
        if parquet_column_names(str(path)) != expected_column_names:
            raise MergeError(
                f"partition {partition_id} artifact schema drifted from the dataset contract"
            )
        return {
            "row_count": rows,
            "filing_record_count": int(recorded.get("filing_record_count") or 0),
            "duplicate_accessions": list(recorded.get("duplicate_accessions") or []),
            "artifact_sha256": digest,
        }

    # Deep path: no trustworthy report — validate the artifact fully once,
    # then regenerate its report with the sha256 for future merges.
    validation = validate_files(con, "parquet", [str(path)], spec)
    _raise_validation_failure(
        validation,
        scope=f"partition {partition_id}",
        expected_rows=partition.get("row_count"),
    )
    keys = ordered_keys(con, "parquet", str(path), spec)
    if keys != partition.get("cik_padded", []):
        raise MergeError(f"partition {partition_id} CIK coverage differs from plan")
    duplicate_accessions = duplicate_values(
        con,
        "parquet",
        [str(path)],
        spec.schema,
        ("filings", "accession_number_normalized"),
    )
    filing_record_count = count_nested_values(
        con,
        "parquet",
        [str(path)],
        spec.schema,
        ("filings", "accession_number_normalized"),
    )
    digest = file_sha256(str(path))
    payload = _partition_report_payload(
        artifacts_dir,
        partition,
        row_count=validation.row_count,
        filing_record_count=filing_record_count,
        duplicate_accessions=duplicate_accessions,
        storage_format="parquet",
        schema_version=spec.schema_version,
        input_fingerprint=spec.fingerprint,
        plan_hash=plan_hash,
        artifact_sha256=digest,
    )
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
    return {
        "row_count": validation.row_count,
        "filing_record_count": filing_record_count,
        "duplicate_accessions": duplicate_accessions,
        "artifact_sha256": digest,
    }


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
    expected_column_names = [field.name for field in spec.schema]
    carried_rows = 0
    carried_filings = 0
    carried_duplicates: set[str] = set()
    carried: dict | None = None
    with connect() as con:
        for partition in ordered_partitions:
            partition_id = partition["partition_id"]
            path = _partition_artifact_path(artifacts_dir, partition_id, "parquet")
            if not path.exists():
                raise MergeError(
                    f"missing partition artifact for partition {partition_id}: {path}"
                )
            carried = _verify_partition_artifact(
                con,
                artifacts_dir,
                partition,
                path,
                spec,
                expected_column_names,
                expected_version,
                expected_fingerprint,
                plan_hash,
            )
            carried_rows += carried["row_count"]
            carried_filings += carried["filing_record_count"]
            carried_duplicates.update(carried["duplicate_accessions"])
            _emit(
                progress,
                {
                    "type": "partition_validated",
                    "partition_id": partition_id,
                    "rows": carried["row_count"],
                },
            )
            logger.info(
                "final merge: partition %d/%d verified (rows=%d, sha256 %s)",
                len(combined_files) + 1,
                len(ordered_partitions),
                carried["row_count"],
                carried["artifact_sha256"][:12],
            )
            combined_files.append(str(path))
        if carried_rows != plan.get("row_count"):
            raise MergeError("merged partition artifacts do not cover the planned CIKs")
        report.duplicate_accessions = sorted(carried_duplicates)
        report.row_count = carried_rows
        report.filing_record_count = carried_filings
        _emit(
            progress,
            {"type": "merge_stage", "stage": "validate", "rows": report.row_count},
        )
        if len(combined_files) == 1:
            # One artifact covers the whole plan and it just passed integrity
            # verification: a byte copy is the exact, fastest publication.
            source_path = combined_files[0]
            if os.path.abspath(source_path) == os.path.abspath(output_path):
                finalized_count = carried_rows
            else:
                os.makedirs(
                    os.path.dirname(os.path.abspath(output_path)), exist_ok=True
                )
                tmp_output = output_path + ".tmp"
                shutil.copyfile(source_path, tmp_output)
                os.replace(tmp_output, output_path)
                finalized_count = count_rows(con, output_path)
            report.artifact_sha256 = carried["artifact_sha256"]
            logger.info(
                "final merge: single-partition fast path, copied %s -> %s",
                source_path,
                output_path,
            )
        else:
            concat_to_parquet(con, artifact_format, combined_files, spec, output_path)
            finalized_count = count_rows(con, output_path)
        _emit(
            progress,
            {"type": "merge_stage", "stage": "publish", "rows": report.row_count},
        )
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

    # Publish to manifests dataset path if running under standard artifacts root
    root = _artifact_root(artifacts_dir, output_path)
    published_path = (
        resolve_paths(env={"ARTIFACTS_ROOT": root})
        .phase("metadata")
        .published_dataset("submission_metadata", "parquet")
    )
    if os.path.abspath(output_path) != os.path.abspath(published_path):
        published_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_pub = str(published_path) + ".tmp"
        shutil.copyfile(output_path, tmp_pub)
        os.replace(tmp_pub, str(published_path))
        _publish_handoff(
            str(published_path),
            artifacts_dir=artifacts_dir,
            row_count=report.row_count,
        )
    else:
        _publish_handoff(
            output_path,
            artifacts_dir=artifacts_dir,
            row_count=report.row_count,
        )
    return report


def _add_duplicate_warning(report: MergeReport) -> None:
    if report.duplicate_accessions:
        report.warnings.append(
            f"{len(report.duplicate_accessions)} duplicate accession(s) observed; "
            "accession is not globally unique"
        )
