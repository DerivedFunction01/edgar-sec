from __future__ import annotations

import json
import inspect
import sqlite3
import tempfile
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from pathlib import PurePosixPath

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.domain.sec_urls import validate_archive_url
from edgar_sec.foundation.hashing import file_sha256, is_sha256_hex_digest
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.pipelines.document_acquisition.body_handoff import (
    get_staged_body_ref,
    read_body_consumption_receipt,
)
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths
from edgar_sec.pipelines.document_acquisition.processing.worker import process_target
from edgar_sec.pipelines.document_acquisition.processing import work_order
from edgar_sec.pipelines.document_acquisition.processing.models import (
    OperationResult,
    ProcessingDiagnostic,
    ProcessingRequest,
    ProcessingResult,
    StagedOutputRef,
)
from edgar_sec.pipelines.document_acquisition.run_state.locks import RunLock
from edgar_sec.pipelines.document_acquisition.run_state.operations import (
    append_operation_attempt,
    get_operation_state,
    iter_operation_states,
    operation_attempt_id,
)
from edgar_sec.pipelines.document_acquisition.run_state.store import (
    get_target_state,
    iter_target_state_pairs,
)
from edgar_sec.pipelines.document_acquisition.run_validation import (
    iter_work_order_rows,
    load_validated_work_order,
)
from edgar_sec.pipelines.document_acquisition.models import OperationAttempt
from edgar_sec.foundation.runtime.paths import validate_safe_id


_PROCESSING_RESULT_SCHEMA_VERSION = 1


class ProcessingRunIntegrationError(RuntimeError):
    pass


_TERMINAL_OPERATION_STATUSES = frozenset(
    {"not_requested", "not_selected", "available", "unsupported", "blocked", "failed"}
)


def _result_manifest_path(paths: AcquisitionPaths, run_id: str, target_id: str) -> Path:
    return (
        paths.run_staging_root(run_id)
        / "processing"
        / f"{validate_safe_id(target_id, 'target_id')}.json"
    )


def _safe_staging_file(
    paths: AcquisitionPaths, run_id: str, relative_path: str, *, strict: bool
) -> Path:
    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or ".." in relative.parts or "\\" in relative_path:
        raise ValueError("processing result staged reference escapes run staging")
    root = paths.run_staging_root(run_id)
    if root.is_symlink():
        raise ValueError("processing run staging root is unsafe")
    candidate = root.joinpath(*relative.parts)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("processing result staged path contains a symlink")
    resolved = candidate.resolve(strict=strict)
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("processing result staged reference escapes run staging")
    if strict and not resolved.is_file():
        raise ValueError("processing result staged output is not a file")
    return resolved


def _body_receipt_verified(paths, body, processing_id: str) -> bool:
    receipt = read_body_consumption_receipt(paths, body.run_id, body.target_id)
    if receipt is None:
        return False
    if (
        receipt["run_id"] != body.run_id
        or receipt["target_id"] != body.target_id
        or receipt["processing_run_id"] != processing_id
        or receipt["source_response_sha256"] != body.source_response_sha256
        or receipt["selected_sha256"] != body.sha256
    ):
        raise ValueError("body consumption receipt differs from processing result")
    return True


def _result_entry(
    paths: AcquisitionPaths,
    run_id: str,
    operation_result,
    operation_row: dict[str, object],
    body,
    processing_id: str,
) -> dict[str, object]:
    staged_output = operation_result.staged_output
    output_ref = None
    if staged_output is not None:
        staging_root = paths.run_staging_root(run_id).resolve()
        if paths.run_staging_root(run_id).is_symlink():
            raise ValueError("processing run staging root is unsafe")
        relative = staged_output.path.relative_to(staging_root).as_posix()
        output_path = _safe_staging_file(paths, run_id, relative, strict=True)
        output_size = output_path.stat().st_size
        if operation_row["operation"] == "raw":
            output_sha256 = body.sha256
            if (
                operation_result.status != "available"
                or staged_output.path != body.path
                or staged_output.staging_id != processing_id
                or staged_output.representation != "raw"
                or output_size != body.byte_size
                or staged_output.output_sha256 != body.sha256
                or staged_output.output_size != body.byte_size
                or operation_result.output_sha256 != body.sha256
                or operation_result.output_size != body.byte_size
            ):
                raise ValueError("raw processing reference differs from selected body")
        else:
            output_sha256 = file_sha256(output_path)
            if (
                output_sha256 != operation_result.output_sha256
                or output_size != operation_result.output_size
            ):
                raise ValueError("processing output metadata differs from staged bytes")
        output_ref = {
            "staging_id": staged_output.staging_id,
            "path": output_path.relative_to(staging_root).as_posix(),
            "representation": staged_output.representation,
            "sha256": output_sha256,
            "byte_size": output_size,
        }
    elif operation_result.status == "available":
        raise ValueError("available processing output has no staged reference")
    return {
        **{key: operation_row[key] for key in work_order.OPERATION_PIN_KEYS},
        "operation_fingerprint": operation_result.operation_fingerprint,
        "status": operation_result.status,
        "representation_id": operation_result.representation_id,
        "output_sha256": operation_result.output_sha256,
        "output_size": operation_result.output_size,
        "result_handler_id": operation_result.handler_id,
        "result_handler_version": operation_result.handler_version,
        "diagnostic_codes": [item.code for item in operation_result.diagnostics],
        "staged_output": output_ref,
    }


def _persist_processing_result(
    paths: AcquisitionPaths,
    target: dict[str, object],
    request: ProcessingRequest,
    result: ProcessingResult,
    rows: tuple[dict[str, object], ...],
) -> None:
    if (
        result.target_id != request.target_id
        or result.source_sha256 != request.body.sha256
    ):
        raise ValueError("processing result identity differs from its request")
    results = {item.operation_id: item for item in result.operation_results}
    row_by_id = {str(row["operation_id"]): row for row in rows}
    if len(results) != len(rows) or set(results) != set(row_by_id):
        raise ValueError("processing result coverage differs from resolved work order")
    assessment = getattr(result, "exhibit_assessment", None)
    assessment_fingerprint = getattr(result, "exhibit_assessment_fingerprint", None)
    manifest = {
        "schema_version": _PROCESSING_RESULT_SCHEMA_VERSION,
        "run_id": request.body.run_id,
        "target_id": request.target_id,
        "processing_id": result.processing_id,
        "source_sha256": result.source_sha256,
        "source_asset_id": result.source_asset_id,
        "exhibit_assessment": (asdict(assessment) if assessment is not None else None),
        "exhibit_assessment_fingerprint": assessment_fingerprint,
        "body_verified_by_processing": _body_receipt_verified(
            paths, request.body, result.processing_id
        ),
        "request_fingerprint": work_order.request_fingerprint(
            target,
            request.body,
            rows,
        ),
        "operations": [
            _result_entry(
                paths,
                request.body.run_id,
                operation_result,
                row_by_id[operation_result.operation_id],
                request.body,
                result.processing_id,
            )
            for operation_result in result.operation_results
        ],
    }
    atomic_write_json(
        _result_manifest_path(paths, request.body.run_id, request.target_id), manifest
    )


def _read_prior_processing_result(
    paths: AcquisitionPaths,
    run_id: str,
    target: dict[str, object],
    body,
    rows: tuple[dict[str, object], ...],
) -> dict[str, object] | None:
    manifest_path = _result_manifest_path(paths, run_id, str(target["target_id"]))
    if not manifest_path.exists():
        return None
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("processing result manifest is unsafe")
    staging_root = paths.run_staging_root(run_id).resolve()
    resolved_manifest = manifest_path.resolve(strict=True)
    if not resolved_manifest.is_relative_to(staging_root):
        raise ValueError("processing result manifest escapes run staging")
    raw = resolved_manifest.read_text(encoding="utf-8")
    manifest = json.loads(raw)
    if not isinstance(manifest, dict) or canonical_json(manifest) != raw:
        raise ValueError("processing result manifest is not canonical JSON")
    if (
        manifest.get("schema_version") != _PROCESSING_RESULT_SCHEMA_VERSION
        or manifest.get("run_id") != run_id
        or manifest.get("target_id") != target["target_id"]
        or manifest.get("source_sha256") != body.sha256
        or not is_sha256_hex_digest(manifest.get("source_sha256"))
        or not is_sha256_hex_digest(manifest.get("request_fingerprint"))
        or manifest.get("request_fingerprint")
        != work_order.request_fingerprint(target, body, rows)
        or not isinstance(manifest.get("processing_id"), str)
        or not manifest["processing_id"]
        or type(manifest.get("body_verified_by_processing")) is not bool
    ):
        raise ValueError("processing result manifest identity differs from work order")
    assessment = manifest.get("exhibit_assessment")
    assessment_fingerprint = manifest.get("exhibit_assessment_fingerprint")
    if (
        (assessment is None) != (assessment_fingerprint is None)
        or (assessment is not None and not isinstance(assessment, dict))
        or (
            assessment_fingerprint is not None
            and not is_sha256_hex_digest(assessment_fingerprint)
        )
    ):
        raise ValueError("processing result diagnostic assessment is invalid")
    if manifest["body_verified_by_processing"] != _body_receipt_verified(
        paths, body, manifest["processing_id"]
    ):
        raise ValueError("processing result receipt verification flag is inconsistent")
    operations = manifest.get("operations")
    if not isinstance(operations, list) or len(operations) != len(rows):
        raise ValueError("processing result manifest operation coverage differs")
    expected = {str(row["operation_id"]): row for row in rows}
    seen = set()
    for entry in operations:
        if not isinstance(entry, dict):
            raise ValueError("processing result manifest operation is invalid")
        operation_id = entry.get("operation_id")
        row = expected.get(operation_id)
        if row is None or operation_id in seen:
            raise ValueError("processing result manifest operation identity differs")
        seen.add(operation_id)
        for name in work_order.OPERATION_PIN_KEYS[1:]:
            if entry.get(name) != row[name]:
                raise ValueError(
                    "processing result manifest pins differ from work order"
                )
        fingerprint = entry.get("operation_fingerprint")
        if not is_sha256_hex_digest(fingerprint):
            raise ValueError("processing result manifest fingerprint is invalid")
        if entry.get("status") not in {
            "not_requested",
            "unsupported",
            "blocked",
            "available",
            "failed",
        }:
            raise ValueError("processing result manifest status is invalid")
        output = entry.get("staged_output")
        if output is None:
            if entry.get("status") == "available":
                raise ValueError("available processing result has no staged output")
            continue
        if not isinstance(output, dict) or not isinstance(output.get("path"), str):
            raise ValueError("processing result staged reference is invalid")
        if row["operation"] == "raw":
            root = paths.run_staging_root(run_id)
            expected_path = body.path.relative_to(root).as_posix()
            resolved = _safe_staging_file(paths, run_id, expected_path, strict=True)
            if (
                entry.get("status") != "available"
                or output["path"] != expected_path
                or output["staging_id"] != manifest["processing_id"]
                or output["representation"] != "raw"
                or output["sha256"] != body.sha256
                or output["byte_size"] != body.byte_size
                or entry.get("output_sha256") != body.sha256
                or entry.get("output_size") != body.byte_size
                or resolved != body.path.resolve(strict=True)
                or resolved.stat().st_size != body.byte_size
            ):
                raise ValueError("raw result reference differs from selected body")
            continue
        resolved = _safe_staging_file(paths, run_id, output["path"], strict=True)
        if (
            not is_sha256_hex_digest(output.get("sha256"))
            or file_sha256(resolved) != output.get("sha256")
            or resolved.stat().st_size != output.get("byte_size")
            or entry.get("output_sha256") != output.get("sha256")
            or entry.get("output_size") != output.get("byte_size")
        ):
            raise ValueError("processing result staged output is missing or corrupt")
    if seen != set(expected):
        raise ValueError("processing result manifest omits resolved operations")
    return manifest


def _prior_results(
    paths: AcquisitionPaths,
    run_id: str,
    manifest: dict[str, object],
    operation_ids: tuple[str, ...],
) -> tuple[OperationResult, ...]:
    results = []
    for entry in manifest["operations"]:
        if (
            entry["status"] not in {"available", "blocked", "failed"}
            or entry["operation_id"] not in operation_ids
        ):
            continue
        output = entry["staged_output"]
        staged_output = None
        if output is not None:
            staged_output = StagedOutputRef(
                staging_id=output["staging_id"],
                path=_safe_staging_file(paths, run_id, output["path"], strict=True),
                representation=output["representation"],
                output_sha256=output["sha256"],
                output_size=output["byte_size"],
            )
        results.append(
            OperationResult(
                operation_id=entry["operation_id"],
                operation_fingerprint=entry["operation_fingerprint"],
                status=entry["status"],
                representation_id=entry["representation_id"],
                output_sha256=entry["output_sha256"],
                output_size=entry["output_size"],
                handler_id=entry["result_handler_id"],
                handler_version=entry["result_handler_version"],
                diagnostics=tuple(
                    ProcessingDiagnostic(code=code, detail="reused")
                    for code in entry["diagnostic_codes"]
                ),
                staged_output=staged_output,
            )
        )
    return tuple(results)


def _process_target(
    request: ProcessingRequest,
    *,
    paths: AcquisitionPaths,
    prior_result: dict[str, object] | None,
    states: dict[str, object],
    retry_failures: bool,
) -> ProcessingResult:
    reused = tuple(
        operation.operation_id
        for operation in request.operations
        if operation.requested
        and states[operation.operation_id].status in {"succeeded", "failed"}
        and not _eligible(states[operation.operation_id], retry_failures)
    )
    if not reused:
        return process_target(request, paths=paths)
    if prior_result is None:
        raise ProcessingRunIntegrationError(
            "completed operation state has no validated result manifest"
        )
    parameters = inspect.signature(process_target).parameters
    if "prior_results" not in parameters or "selected_operation_ids" not in parameters:
        raise ProcessingRunIntegrationError(
            "operation-scoped retry requires process_target prior_results and selected-operation support"
        )
    selected_operation_ids = tuple(
        operation.operation_id
        for operation in request.operations
        if operation.requested
        and _eligible(states[operation.operation_id], retry_failures)
    )
    return process_target(
        request,
        paths=paths,
        prior_results=_prior_results(paths, request.body.run_id, prior_result, reused),
        selected_operation_ids=selected_operation_ids,
    )


def _read_relation_spool(
    paths: AcquisitionPaths, run_id: str
) -> tuple[tempfile.TemporaryDirectory, sqlite3.Connection]:
    temporary_directory = tempfile.TemporaryDirectory(prefix="acquisition-processing-")
    database_path = Path(temporary_directory.name) / "work-order.sqlite"
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("PRAGMA temp_store=FILE")
        connection.row_factory = sqlite3.Row
        work_order.stream_resolved_operations(connection, paths, run_id)
        connection.commit()
        return temporary_directory, connection
    except Exception:
        connection.close()
        temporary_directory.cleanup()
        raise


def _operation_status(state) -> str:
    if state.status in {"not_requested", "not_selected", "blocked", "unsupported"}:
        return state.status
    if state.status == "succeeded":
        return "available"
    if state.status == "pending":
        return "pending"
    error_code = state.error_code or ""
    for status in ("blocked", "unsupported", "failed"):
        if error_code.startswith(f"{status}:"):
            return status
    return "failed"


def _eligible(state, retry_failures: bool) -> bool:
    return state.status == "pending" or (
        retry_failures and state.status == "failed" and state.retryable
    )


def _record_attempt(
    database_path: Path,
    operation_id: str,
    *,
    status: str,
    error_code: str | None,
    retryable: bool,
    started_at: str,
    finished_at: str,
) -> None:
    state = get_operation_state(database_path, operation_id)
    if state is None:
        raise ValueError("work-order operation state is missing")
    append_operation_attempt(
        database_path,
        OperationAttempt(
            attempt_id=operation_attempt_id(operation_id, state.attempt_count + 1),
            operation_id=operation_id,
            attempt_number=state.attempt_count + 1,
            outcome="succeeded" if status == "available" else "failed",
            retryable=retryable,
            error_code=None
            if status == "available"
            else f"{status}:{error_code or status}",
            started_at_utc=started_at,
            finished_at_utc=finished_at,
        ),
    )


def _target_result_attempts(
    result,
    request: ProcessingRequest,
    states: dict[str, object],
    *,
    retry_failures: bool,
    started_at: str,
    finished_at: str,
    database_path: Path,
) -> None:
    if result.target_id != request.target_id:
        raise ValueError("processing result target differs from request")
    results = {item.operation_id: item for item in result.operation_results}
    if len(results) != len(request.operations) or set(results) != set(states):
        raise ValueError("processing result operation coverage differs from work order")
    for operation in request.operations:
        state = states[operation.operation_id]
        if not operation.requested or not _eligible(state, retry_failures):
            continue
        outcome = results[operation.operation_id]
        status = outcome.status
        if status == "available":
            error_code = None
            retryable = False
        elif status == "unsupported":
            error_code = outcome.diagnostics[0].code if outcome.diagnostics else status
            retryable = False
        elif status == "blocked":
            error_code = outcome.diagnostics[0].code if outcome.diagnostics else status
            retryable = False
        elif status == "failed":
            error_code = outcome.diagnostics[0].code if outcome.diagnostics else status
            retryable = error_code.startswith("handler_failed:")
        else:
            raise ValueError("requested operation did not reach a terminal status")
        _record_attempt(
            database_path,
            operation.operation_id,
            status=status,
            error_code=error_code,
            retryable=retryable,
            started_at=started_at,
            finished_at=finished_at,
        )


def process_acquired_target(
    target: dict[str, object],
    *,
    paths: AcquisitionPaths,
    retry_failures: bool,
    relation_connection: sqlite3.Connection,
    operation_states_path: Path,
) -> bool:
    target_id = str(target["target_id"])
    target_state = get_target_state(operation_states_path, target_id)
    if target_state is None or target_state.outcome != "acquired":
        return False
    rows = work_order.resolved_operations(relation_connection, target_id)
    states = {
        operation_state.operation_id: operation_state
        for operation_state in iter_operation_states(operation_states_path, target_id)
    }
    if set(states) != {str(row["operation_id"]) for row in rows}:
        raise ValueError("operation state disagrees with pinned work order")
    body = get_staged_body_ref(paths, str(target["run_id"]), target_id)
    request = ProcessingRequest(
        target_id=target_id,
        accession=AccessionNumber.from_any(target["accession"]),
        form=str(target["form"]),
        target_role=target["target_role"],
        target_type=str(target["target_type"]),
        document_path=validate_archive_url(
            str(target["target_url"]), AccessionNumber.from_any(target["accession"])
        ).document_path,
        selected_filename=body.selected_filename,
        source_origin=target["source_origin"],
        body=body,
        operations=work_order.operation_requests(rows),
    )
    prior_result = _read_prior_processing_result(
        paths, str(target["run_id"]), target, body, rows
    )
    eligible = any(
        row["requested"] and _eligible(states[str(row["operation_id"])], retry_failures)
        for row in rows
    )
    if not eligible:
        if prior_result is None and any(
            state.status == "succeeded" for state in states.values()
        ):
            raise ValueError("completed operations have no result manifest")
        return False
    started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    try:
        result = _process_target(
            request,
            paths=paths,
            prior_result=prior_result,
            states=states,
            retry_failures=retry_failures,
        )
    except ProcessingRunIntegrationError:
        raise
    except Exception:
        finished_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        for operation in request.operations:
            state_for_operation = states[operation.operation_id]
            if operation.requested and _eligible(state_for_operation, retry_failures):
                _record_attempt(
                    operation_states_path,
                    operation.operation_id,
                    status="failed",
                    error_code="target_processing_failed",
                    retryable=False,
                    started_at=started_at,
                    finished_at=finished_at,
                )
        return True
    finished_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    _persist_processing_result(paths, target, request, result, rows)
    _target_result_attempts(
        result,
        request,
        states,
        retry_failures=retry_failures,
        started_at=started_at,
        finished_at=finished_at,
        database_path=operation_states_path,
    )
    return True


def execute_processing_run(
    run_id: str,
    paths: AcquisitionPaths,
    *,
    retry_failures: bool = False,
    workers: int | None = None,
) -> dict:
    if type(retry_failures) is not bool:
        raise ValueError("retry_failures must be a boolean")
    if workers is not None and (type(workers) is not int or workers < 1):
        raise ValueError("workers must be a positive integer")
    target_parts = load_validated_work_order(paths, run_id)
    operation_states_path = paths.run_state_path(run_id)
    attempted_targets = 0
    temporary_directory = None
    relation_connection = None
    try:
        with RunLock(paths.run_lock_path(run_id), run_id):
            target_parts = load_validated_work_order(paths, run_id)
            temporary_directory, relation_connection = _read_relation_spool(
                paths, run_id
            )
            for target, state in iter_target_state_pairs(
                operation_states_path, iter_work_order_rows(target_parts)
            ):
                target_id = str(target["target_id"])
                if state is None or state.target_id != target_id:
                    raise ValueError("target state disagrees with pinned work order")
                if (
                    state.executable != (target["executable"] is True)
                    or state.skip_reason != target["skip_reason"]
                ):
                    raise ValueError("target state disagrees with pinned work order")
                if state.outcome != "acquired":
                    continue
                if process_acquired_target(
                    target | {"run_id": run_id},
                    paths=paths,
                    retry_failures=retry_failures,
                    relation_connection=relation_connection,
                    operation_states_path=operation_states_path,
                ):
                    attempted_targets += 1
            target_counts: Counter[str] = Counter()
            for _, state in iter_target_state_pairs(
                operation_states_path, iter_work_order_rows(target_parts)
            ):
                target_counts[state.outcome if state is not None else "missing"] += 1
            operation_counts: Counter[str] = Counter()
            for state in iter_operation_states(operation_states_path):
                operation_counts[_operation_status(state)] += 1
            complete = all(
                status in _TERMINAL_OPERATION_STATUSES for status in operation_counts
            )
    finally:
        if relation_connection is not None:
            relation_connection.close()
        if temporary_directory is not None:
            temporary_directory.cleanup()

    failures = operation_counts.get("failed", 0)
    blocked = operation_counts.get("blocked", 0)
    unsupported = operation_counts.get("unsupported", 0)
    return {
        "success": complete and failures == 0 and blocked == 0 and unsupported == 0,
        "complete": complete,
        "run_id": run_id,
        "target_counts": dict(sorted(target_counts.items())),
        "operation_counts": dict(sorted(operation_counts.items())),
        "attempted_target_count": attempted_targets,
    }
