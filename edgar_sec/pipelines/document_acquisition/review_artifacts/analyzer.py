from __future__ import annotations

import json
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

from edgar_sec.foundation.hashing import file_sha256, is_sha256_hex_digest
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.infra.storage.review.paths import PIPELINE_REVIEW_MANIFEST_FILE

_CASE_STATUSES = {
    "complete",
    "fixture_verification_failure",
    "execution_error",
}
_OPERATION_STATUSES = {
    "not_requested",
    "not_selected",
    "unsupported",
    "blocked",
    "available",
    "failed",
}


class ReviewAnalysisError(ValueError):
    pass


def _load_artifact(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    outputs = record.get("outputs")
    if not isinstance(outputs, dict) or set(outputs) != {"processing-review.json"}:
        raise ReviewAnalysisError("completed case has invalid artifact references")
    reference = outputs["processing-review.json"]
    if (
        not isinstance(reference, dict)
        or set(reference) != {"path", "sha256"}
        or not isinstance(reference.get("path"), str)
        or not is_sha256_hex_digest(reference.get("sha256"))
    ):
        raise ReviewAnalysisError("completed case has malformed artifact reference")
    relative = PurePosixPath(reference["path"])
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or "\\" in reference["path"]
        or len(relative.parts) != 3
        or relative.parts[0] != "cases"
        or relative.parts[2] != "processing-review.json"
    ):
        raise ReviewAnalysisError("case artifact path is unsafe")
    artifact_path = root.joinpath(*relative.parts)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ReviewAnalysisError("case artifact path contains a symlink")
    if not artifact_path.is_file() or not artifact_path.resolve().is_relative_to(
        root.resolve()
    ):
        raise ReviewAnalysisError("case artifact is missing or escapes its run")
    if file_sha256(artifact_path) != reference["sha256"]:
        raise ReviewAnalysisError("case artifact digest differs from manifest")
    try:
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReviewAnalysisError("case artifact is unreadable") from error
    if not isinstance(artifact, dict):
        raise ReviewAnalysisError("case artifact must be a JSON object")
    if (
        artifact.get("artifact_type") != "document_acquisition.processing_review"
        or artifact.get("artifact_version") != 1
    ):
        raise ReviewAnalysisError("case artifact format is unsupported")
    digest = artifact.get("artifact_sha256")
    unsigned = dict(artifact)
    unsigned.pop("artifact_sha256", None)
    if digest != canonical_hash(unsigned):
        raise ReviewAnalysisError("case artifact content digest is invalid")
    fixture = artifact.get("fixture")
    if (
        not isinstance(fixture, dict)
        or fixture.get("fixture_id") != record.get("fixture_id")
        or fixture.get("capture_id") != record.get("capture_id")
        or fixture.get("target_id") != record.get("target_id")
        or fixture.get("target_plan_id") != record.get("target_plan_id")
        or fixture.get("target_plan_digest") != record.get("target_plan_digest")
        or fixture.get("target_plan_schema_version")
        != record.get("target_plan_schema_version")
        or fixture.get("capture_run_id") != record.get("run_id")
        or artifact.get("accession") != record.get("accession")
        or artifact.get("target_id") != record.get("target_id")
        or artifact.get("run_id") != record.get("run_id")
    ):
        raise ReviewAnalysisError("case artifact identity differs from manifest")
    return artifact


def analyze_review_run(run: str | Path) -> dict[str, Any]:
    requested_root = Path(run).expanduser()
    if requested_root.is_symlink():
        raise ReviewAnalysisError("review run must not be a symlink")
    root = requested_root.resolve(strict=True)
    if not root.is_dir():
        raise ReviewAnalysisError("review run must be a real directory")
    manifest = root / PIPELINE_REVIEW_MANIFEST_FILE
    if manifest.is_symlink() or not manifest.is_file():
        raise ReviewAnalysisError("review manifest is missing or unsafe")
    statuses: Counter[str] = Counter()
    operations: Counter[str] = Counter()
    seen: set[tuple[str, str, str]] = set()
    previous: tuple[str, str, str] | None = None
    total = 0
    try:
        with manifest.open("r", encoding="utf-8") as stream:
            for line in stream:
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ReviewAnalysisError("review manifest record is not an object")
                identity = (
                    record.get("fixture_id"),
                    record.get("capture_id"),
                    record.get("target_id"),
                )
                if not all(isinstance(value, str) and value for value in identity):
                    raise ReviewAnalysisError(
                        "review manifest case identity is invalid"
                    )
                if identity in seen or (previous is not None and identity < previous):
                    raise ReviewAnalysisError(
                        "review manifest cases are duplicated or unsorted"
                    )
                seen.add(identity)
                previous = identity
                if record.get("review_id") != root.name:
                    raise ReviewAnalysisError("review manifest run identity differs")
                status = record.get("status")
                if not isinstance(status, str) or status not in _CASE_STATUSES:
                    raise ReviewAnalysisError("review manifest case status is invalid")
                if (
                    not isinstance(record.get("run_id"), str)
                    or not record["run_id"]
                    or not isinstance(record.get("target_plan_id"), str)
                    or not record["target_plan_id"]
                    or not is_sha256_hex_digest(record.get("target_plan_digest"))
                    or type(record.get("target_plan_schema_version")) is not int
                    or record["target_plan_schema_version"] < 1
                ):
                    raise ReviewAnalysisError(
                        "review manifest plan provenance is invalid"
                    )
                total += 1
                statuses[status] += 1
                if status == "complete":
                    artifact = _load_artifact(root, record)
                    processing = artifact.get("processing")
                    values = (
                        processing.get("operations")
                        if isinstance(processing, dict)
                        else None
                    )
                    if not isinstance(values, list):
                        raise ReviewAnalysisError("case operation results are missing")
                    operation_ids: set[str] = set()
                    for operation in values:
                        if (
                            not isinstance(operation, dict)
                            or not isinstance(operation.get("operation_id"), str)
                            or not operation["operation_id"]
                            or not isinstance(operation.get("status"), str)
                            or operation.get("status") not in _OPERATION_STATUSES
                            or operation["operation_id"] in operation_ids
                        ):
                            raise ReviewAnalysisError(
                                "case operation result is invalid"
                            )
                        operation_ids.add(operation["operation_id"])
                        operations[operation["status"]] += 1
                elif record.get("outputs") != {}:
                    raise ReviewAnalysisError(
                        "failed case unexpectedly references outputs"
                    )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReviewAnalysisError("review manifest is unreadable") from error
    if total == 0:
        raise ReviewAnalysisError("review manifest has no cases")
    return {
        "review_id": root.name,
        "total_cases": total,
        "case_status_counts": {key: statuses[key] for key in sorted(statuses)},
        "operation_status_counts": {key: operations[key] for key in sorted(operations)},
    }


def analyze_review_runs(
    runs: tuple[str | Path, ...], *, output: Path | None = None
) -> dict[str, Any]:
    if not runs:
        raise ReviewAnalysisError("at least one review run is required")
    results = [analyze_review_run(run) for run in runs]
    if len({item["review_id"] for item in results}) != len(results):
        raise ReviewAnalysisError("review run IDs must be unique")
    results.sort(key=lambda item: item["review_id"])
    report = {"schema_version": 1, "runs": results}
    if output is not None:
        output_path = Path(output).expanduser()
        resolved_output = output_path.resolve()
        if any(
            resolved_output.is_relative_to(Path(run).expanduser().resolve())
            for run in runs
        ):
            raise ReviewAnalysisError(
                "analysis output must be separate from review runs"
            )
        atomic_write_json(output_path, report)
    return report


__all__ = ["ReviewAnalysisError", "analyze_review_run", "analyze_review_runs"]
