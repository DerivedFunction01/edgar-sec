from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import tempfile
from collections.abc import Iterable, Iterator
from pathlib import Path
from pathlib import PurePosixPath
from urllib.parse import quote

import pyarrow as pa

from edgar_sec.domain.document.route import DocumentRoute
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.domain.sec_urls import validate_archive_url
from edgar_sec.foundation.hashing import is_sha256_hex_digest
from edgar_sec.foundation.io import DEFAULT_IO_CHUNK_SIZE
from edgar_sec.foundation.runtime.paths import validate_safe_id
from edgar_sec.foundation.runtime.settings.sql import resolve_sql_insert_batch_size
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.pipelines.document_acquisition.body_handoff import (
    BodyHandoffError,
    get_staged_body_ref,
)
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths
from edgar_sec.pipelines.document_acquisition.processing_models import (
    OperationRequest,
    ProcessingRequest,
    ProcessingResult,
)
from edgar_sec.pipelines.document_acquisition.projection_models import (
    ProcessingResultProjection,
    ProjectedOperation,
    ProjectedTarget,
    ResultProjectionError,
    fingerprint_targets,
    projected_target_record,
    request_from_record,
    request_record,
    result_from_record,
    result_record,
)
from edgar_sec.pipelines.document_acquisition.run_validation import (
    iter_work_order_rows,
    load_validated_work_order,
)


_TERMINAL_STATUSES = frozenset(
    {"not_requested", "unsupported", "blocked", "available", "failed"}
)
_EXECUTION_STATUSES = frozenset({"available", "failed", "blocked", "unsupported"})
_WORK_TARGET_COLUMNS = (
    "target_id",
    "accession",
    "form",
    "target_role",
    "target_type",
    "source_origin",
    "executable",
    "status",
    "retrieval_mode",
    "target_url",
)


def _validate_request(request: ProcessingRequest, run_id: str) -> None:
    try:
        validate_safe_id(request.target_id, "target_id")
    except ValueError as error:
        raise ResultProjectionError("processing target ID is invalid") from error
    if request.body.run_id != run_id or request.body.target_id != request.target_id:
        raise ResultProjectionError("processing request body identity is inconsistent")
    if not request.operations:
        raise ResultProjectionError("processing request has no explicit operations")
    operation_ids = set()
    for operation in request.operations:
        _validate_operation_request(operation)
        if operation.operation_id in operation_ids:
            raise ResultProjectionError("processing request operation is duplicated")
        operation_ids.add(operation.operation_id)


def _validate_result(result: ProcessingResult) -> None:
    try:
        validate_safe_id(result.target_id, "target_id")
        validate_safe_id(result.processing_id, "processing_id")
    except ValueError as error:
        raise ResultProjectionError("processing result identity is invalid") from error
    if not isinstance(result.route, DocumentRoute):
        raise ResultProjectionError("processing route is invalid")


def _validate_operation_request(operation: OperationRequest) -> None:
    try:
        validate_safe_id(operation.operation_id, "operation_id")
    except ValueError as error:
        raise ResultProjectionError("operation ID is invalid") from error
    if operation.operation not in {"raw", "render_to_txt", "render_to_xml"}:
        raise ResultProjectionError("operation name is invalid")
    if type(operation.requested) is not bool:
        raise ResultProjectionError("operation requested flag is invalid")
    if operation.support_status not in {"supported", "unsupported", "not_evaluated"}:
        raise ResultProjectionError("operation support status is invalid")


def _stage_work_order(
    connection: sqlite3.Connection, paths: AcquisitionPaths, run_id: str
) -> None:
    try:
        parts = load_validated_work_order(paths, run_id)
        insert_batch_size = resolve_sql_insert_batch_size()
        for row_number, row in enumerate(iter_work_order_rows(parts), start=1):
            connection.execute(
                "INSERT INTO work_targets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                tuple(row[column] for column in _WORK_TARGET_COLUMNS),
            )
            if row_number % insert_batch_size == 0:
                connection.commit()
        connection.commit()
    except ResultProjectionError:
        raise
    except sqlite3.IntegrityError as error:
        if "work_targets.target_id" in str(error):
            raise ResultProjectionError("target is duplicated in work order") from error
        raise ResultProjectionError("validated work order is unavailable") from error
    except (OSError, ValueError, TypeError, sqlite3.Error, pa.ArrowException) as error:
        raise ResultProjectionError("validated work order is unavailable") from error


def _validate_work_target(request: ProcessingRequest, row: dict[str, object]) -> None:
    accession = AccessionNumber.from_any(request.accession)
    if (
        row["target_id"] != request.target_id
        or AccessionNumber.from_any(str(row["accession"])) != accession
        or row["form"] != request.form
        or row["target_role"] != request.target_role
        or row["target_type"] != request.target_type
        or row["source_origin"] != request.source_origin
        or row["executable"] is not True
        or row["status"] != "matched"
    ):
        raise ResultProjectionError("processing request differs from work order")
    if row["retrieval_mode"] not in {"direct_url", "bundle_sequence"}:
        raise ResultProjectionError("work-order target is not processable")
    if row["retrieval_mode"] == "bundle_sequence":
        raise ResultProjectionError(
            "bundle result projection requires committed selected-filename evidence"
        )
    try:
        target = validate_archive_url(str(row["target_url"]), accession)
    except ValueError as error:
        raise ResultProjectionError("work-order target URL is invalid") from error
    if request.document_path != target.document_path:
        raise ResultProjectionError("processing path differs from work order")


def _relative_staging_path(path: Path, paths: AcquisitionPaths, run_id: str) -> str:
    try:
        if not path.is_absolute():
            raise ValueError("staged path is not absolute")
        run_dir = paths.run_dir(run_id)
        if stat.S_ISLNK(run_dir.lstat().st_mode):
            raise ValueError("run directory is a symlink")
        staging_root = paths.run_staging_root(run_id)
        if stat.S_ISLNK(staging_root.lstat().st_mode):
            raise ValueError("staging root is a symlink")
        relative = path.relative_to(staging_root)
        if any(part in {"", ".", ".."} for part in relative.parts):
            raise ValueError("staged path is not canonical")
        resolved_root = staging_root.resolve(strict=True)
        resolved_path = path.resolve(strict=True)
        resolved_path.relative_to(resolved_root)
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError("staged path is not a regular file")
        for parent in path.parents:
            if parent == staging_root.parent:
                break
            if stat.S_ISLNK(parent.lstat().st_mode):
                raise ValueError("staged path contains a symlink")
    except (OSError, ValueError) as error:
        raise ResultProjectionError(
            "staged output path escapes the run staging root"
        ) from error
    return path.relative_to(run_dir).as_posix()


def _verify_staged_output(
    output: StagedOutputRef,
    *,
    paths: AcquisitionPaths,
    run_id: str,
    processing_id: str,
) -> str:
    if output.staging_id != processing_id:
        raise ResultProjectionError("staged output owner differs from processing ID")
    if not is_sha256_hex_digest(output.output_sha256) or output.output_size < 0:
        raise ResultProjectionError("staged output digest or size is invalid")
    relative_path = _relative_staging_path(output.path, paths, run_id)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(output.path, flags)
    except OSError as error:
        raise ResultProjectionError("staged output cannot be opened safely") from error
    digest = hashlib.sha256()
    size = 0
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ResultProjectionError("staged output is not a regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            while chunk := stream.read(DEFAULT_IO_CHUNK_SIZE):
                digest.update(chunk)
                size += len(chunk)
    finally:
        os.close(descriptor)
    if (digest.hexdigest(), size) != (output.output_sha256, output.output_size):
        raise ResultProjectionError("staged output digest or size differs from result")
    return relative_path


def _effective_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ResultProjectionError("effective path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ResultProjectionError("effective path is unsafe")
    return path.as_posix()


def _project_operation(
    operation: OperationRequest,
    result: OperationResult,
    *,
    paths: AcquisitionPaths,
    run_id: str,
    processing_id: str,
    source_sha256: str,
    source_size: int,
) -> ProjectedOperation:
    if result.operation_id != operation.operation_id:
        raise ResultProjectionError("operation result identity differs from request")
    if result.status not in _TERMINAL_STATUSES:
        raise ResultProjectionError("operation result is not terminal")
    if not is_sha256_hex_digest(result.operation_fingerprint):
        raise ResultProjectionError("operation fingerprint is invalid")
    if not operation.requested and result.status != "not_requested":
        raise ResultProjectionError("unrequested operation has an execution result")
    if operation.requested and result.status == "not_requested":
        raise ResultProjectionError("requested operation is marked not requested")
    if operation.requested and operation.support_status == "unsupported":
        if result.status != "unsupported":
            raise ResultProjectionError(
                "unsupported request has a different result status"
            )
    if operation.requested and operation.support_status == "not_evaluated":
        if result.status != "blocked":
            raise ResultProjectionError("unevaluated request is not blocked")
    if any(
        not isinstance(item.code, str)
        or not item.code
        or not isinstance(item.detail, str)
        for item in result.diagnostics
    ):
        raise ResultProjectionError("operation diagnostic is invalid")
    if result.status in {"failed", "blocked", "unsupported"} and not result.diagnostics:
        raise ResultProjectionError("non-available operation lacks a diagnostic")
    output_path = None
    if result.status == "available":
        if (
            result.representation_id is None
            or not is_sha256_hex_digest(result.output_sha256 or "")
            or result.output_size is None
            or result.output_size < 0
            or result.staged_output is None
        ):
            raise ResultProjectionError("available operation lacks output identity")
        if (
            result.staged_output.output_sha256 != result.output_sha256
            or result.staged_output.output_size != result.output_size
        ):
            raise ResultProjectionError("staged output differs from operation result")
        if (
            not isinstance(result.staged_output.representation, str)
            or not result.staged_output.representation
        ):
            raise ResultProjectionError("staged output representation is invalid")
        if operation.operation == "raw" and (
            result.staged_output.representation != "raw"
            or result.output_sha256 != source_sha256
            or result.output_size != source_size
        ):
            raise ResultProjectionError("raw result is not an identity representation")
        if (
            operation.operation == "render_to_txt"
            and result.handler_id == "text_passthrough"
            and (
                result.staged_output.representation != "text_verbatim"
                or result.output_sha256 != source_sha256
                or result.output_size != source_size
            )
        ):
            raise ResultProjectionError("text passthrough differs from source identity")
        output_path = _verify_staged_output(
            result.staged_output,
            paths=paths,
            run_id=run_id,
            processing_id=processing_id,
        )
    elif any(
        value is not None
        for value in (
            result.representation_id,
            result.output_sha256,
            result.output_size,
            result.staged_output,
        )
    ):
        raise ResultProjectionError("non-available operation claims an output")
    return ProjectedOperation(
        operation_id=result.operation_id,
        status=result.status,
        operation_fingerprint=result.operation_fingerprint,
        representation_id=result.representation_id,
        output_sha256=result.output_sha256,
        output_size=result.output_size,
        handler_id=result.handler_id,
        handler_version=result.handler_version,
        diagnostics=result.diagnostics,
        staged_output_representation=(
            result.staged_output.representation if result.staged_output else None
        ),
        staged_output_path=output_path,
    )


def _project_target(
    request: ProcessingRequest,
    result: ProcessingResult,
    *,
    paths: AcquisitionPaths,
    run_id: str,
) -> ProjectedTarget:
    if result.target_id != request.target_id:
        raise ResultProjectionError("processing result target differs from request")
    if not is_sha256_hex_digest(result.source_sha256):
        raise ResultProjectionError("processing source digest is invalid")
    if result.source_sha256 != request.body.sha256:
        raise ResultProjectionError("processing result source differs from staged body")
    if not is_sha256_hex_digest(request.body.source_response_sha256):
        raise ResultProjectionError("source response digest is invalid")
    try:
        validate_safe_id(result.source_asset_id, "source_asset_id")
    except ValueError as error:
        raise ResultProjectionError("source asset ID is invalid") from error
    if not isinstance(result.route, DocumentRoute):
        raise ResultProjectionError("processing route is invalid")
    effective_path = _effective_path(result.effective_path)
    operations = {item.operation_id: item for item in result.operation_results}
    if len(operations) != len(result.operation_results):
        raise ResultProjectionError("operation result ID is duplicated")
    expected_operations = {item.operation_id: item for item in request.operations}
    if operations.keys() != expected_operations.keys():
        raise ResultProjectionError("operation result set is incomplete or unexpected")
    projected_operations = tuple(
        _project_operation(
            expected_operations[operation_id],
            operations[operation_id],
            paths=paths,
            run_id=run_id,
            processing_id=result.processing_id,
            source_sha256=request.body.sha256,
            source_size=request.body.byte_size,
        )
        for operation_id in sorted(operations)
    )
    verified = get_staged_body_ref(paths, run_id, request.target_id)
    if verified != request.body:
        raise ResultProjectionError("processing request body differs from S9 handoff")
    if request.selected_filename != verified.selected_filename:
        raise ResultProjectionError("selected filename differs from S9 handoff")
    source_path = _relative_staging_path(verified.path, paths, run_id)
    return ProjectedTarget(
        target_id=request.target_id,
        accession=str(request.accession),
        form=request.form,
        target_role=request.target_role,
        target_type=request.target_type,
        source_origin=request.source_origin,
        document_path=request.document_path,
        selected_filename=request.selected_filename,
        source_sha256=result.source_sha256,
        source_response_sha256=verified.source_response_sha256,
        source_size=verified.byte_size,
        source_asset_id=result.source_asset_id,
        source_staged_path=source_path,
        route=result.route,
        effective_path=effective_path,
        processing_id=result.processing_id,
        operations=projected_operations,
    )


def project_terminal_results(
    requests: Iterable[ProcessingRequest],
    results: Iterable[ProcessingResult],
    *,
    paths: AcquisitionPaths,
    run_id: str,
) -> ProcessingResultProjection:
    """Project an explicit acquired-target request/result set without worker checks."""
    temporary_directory = tempfile.TemporaryDirectory(
        prefix="document-acquisition-projection-"
    )
    input_database_path = Path(temporary_directory.name) / "input.sqlite"
    database_path = Path(temporary_directory.name) / "projection.sqlite"
    connection = None
    output_connection = None
    preserve_temporary_directory = False
    try:
        validate_safe_id(run_id, "run_id")
        connection = sqlite3.connect(input_database_path)
        connection.execute("PRAGMA temp_store=FILE")
        connection.execute(
            "CREATE TABLE requests (target_id TEXT PRIMARY KEY, record_json TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE results (target_id TEXT PRIMARY KEY, processing_id TEXT UNIQUE NOT NULL, record_json TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE work_targets ("
            "target_id TEXT PRIMARY KEY, accession TEXT NOT NULL, form TEXT NOT NULL, "
            "target_role TEXT NOT NULL, target_type TEXT NOT NULL, "
            "source_origin TEXT NOT NULL, executable INTEGER NOT NULL, "
            "status TEXT NOT NULL, retrieval_mode TEXT, target_url TEXT)"
        )
        output_connection = sqlite3.connect(database_path)
        output_connection.execute("PRAGMA temp_store=FILE")
        output_connection.execute(
            "CREATE TABLE projected_targets (target_id TEXT PRIMARY KEY, record_json TEXT NOT NULL)"
        )
        insert_batch_size = resolve_sql_insert_batch_size()
        for request_number, request in enumerate(requests, start=1):
            _validate_request(request, run_id)
            try:
                connection.execute(
                    "INSERT INTO requests VALUES (?, ?)",
                    (request.target_id, canonical_json(request_record(request))),
                )
            except sqlite3.IntegrityError as error:
                raise ResultProjectionError(
                    "processing request target is duplicated"
                ) from error
            if request_number % insert_batch_size == 0:
                connection.commit()
        connection.commit()
        for result_number, result in enumerate(results, start=1):
            _validate_result(result)
            try:
                connection.execute(
                    "INSERT INTO results VALUES (?, ?, ?)",
                    (
                        result.target_id,
                        result.processing_id,
                        canonical_json(result_record(result)),
                    ),
                )
            except sqlite3.IntegrityError as error:
                duplicated_target = connection.execute(
                    "SELECT 1 FROM results WHERE target_id = ?", (result.target_id,)
                ).fetchone()
                if duplicated_target is not None:
                    raise ResultProjectionError(
                        "processing result target is duplicated"
                    ) from error
                if "processing_id" in str(error):
                    raise ResultProjectionError(
                        "processing ID is duplicated"
                    ) from error
                raise ResultProjectionError(
                    "processing result target is duplicated"
                ) from error
            if result_number % insert_batch_size == 0:
                connection.commit()
        connection.commit()
        request_count = int(
            connection.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
        )
        result_count = int(
            connection.execute("SELECT COUNT(*) FROM results").fetchone()[0]
        )
        missing_results, unexpected_results = connection.execute(
            "SELECT "
            "(SELECT COUNT(*) FROM requests AS request "
            "LEFT JOIN results AS result USING (target_id) "
            "WHERE result.target_id IS NULL), "
            "(SELECT COUNT(*) FROM results AS result "
            "LEFT JOIN requests AS request USING (target_id) "
            "WHERE request.target_id IS NULL)"
        ).fetchone()
        if request_count != result_count or missing_results or unexpected_results:
            raise ResultProjectionError(
                "terminal processing result coverage is incomplete"
            )
        _stage_work_order(connection, paths, run_id)
        missing_work_targets = int(
            connection.execute(
                "SELECT COUNT(*) FROM requests AS request "
                "LEFT JOIN work_targets AS work USING (target_id) "
                "WHERE work.target_id IS NULL"
            ).fetchone()[0]
        )
        if missing_work_targets:
            raise ResultProjectionError(
                "processing request target is absent from work order"
            )
        connection.commit()

        def projected_targets() -> Iterator[ProjectedTarget]:
            read_connection = sqlite3.connect(
                f"file:{quote(str(input_database_path.resolve()))}?mode=ro", uri=True
            )
            try:
                read_connection.execute("PRAGMA temp_store=FILE")
                cursor = read_connection.execute(
                    "SELECT request.record_json, result.record_json, "
                    "work.target_id, work.accession, work.form, work.target_role, "
                    "work.target_type, work.source_origin, work.executable, "
                    "work.status, work.retrieval_mode, work.target_url "
                    "FROM requests AS request "
                    "JOIN results AS result USING (target_id) "
                    "JOIN work_targets AS work USING (target_id) "
                    "ORDER BY request.target_id"
                )
                for row_number, row in enumerate(cursor, start=1):
                    request_json, result_json = row[0], row[1]
                    request = request_from_record(json.loads(request_json))
                    result = result_from_record(json.loads(result_json))
                    work_target = {
                        name: bool(row[index]) if name == "executable" else row[index]
                        for index, name in enumerate(_WORK_TARGET_COLUMNS, start=2)
                    }
                    _validate_work_target(request, work_target)
                    target = _project_target(
                        request, result, paths=paths, run_id=run_id
                    )
                    output_connection.execute(
                        "INSERT INTO projected_targets VALUES (?, ?)",
                        (
                            target.target_id,
                            canonical_json(projected_target_record(target)),
                        ),
                    )
                    if row_number % insert_batch_size == 0:
                        output_connection.commit()
                    yield target
            finally:
                read_connection.close()

        fingerprint = fingerprint_targets(run_id, projected_targets())
        output_connection.commit()
        connection.close()
        connection = None
        output_connection.close()
        output_connection = None
        input_database_path.unlink(missing_ok=True)
        preserve_temporary_directory = True
        return ProcessingResultProjection(
            run_id=run_id,
            fingerprint=fingerprint,
            _database_path=database_path,
            _temporary_directory=temporary_directory,
        )
    except ResultProjectionError:
        raise
    except (
        BodyHandoffError,
        OSError,
        TypeError,
        ValueError,
        sqlite3.Error,
        pa.ArrowException,
    ) as error:
        raise ResultProjectionError(
            "terminal processing results failed validation"
        ) from error
    finally:
        if connection is not None:
            connection.close()
        if output_connection is not None:
            output_connection.close()
        if not preserve_temporary_directory:
            temporary_directory.cleanup()


__all__ = [
    "project_terminal_results",
]
