from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from edgar_sec.domain.document.route import DocumentRoute
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.pipelines.document_acquisition import result_projection
from edgar_sec.pipelines.document_acquisition.paths import (
    AcquisitionPaths,
    resolve_acquisition_paths,
)
from edgar_sec.pipelines.document_acquisition.projection_models import (
    ResultProjectionError,
    projected_target_record,
)
from edgar_sec.pipelines.document_acquisition.processing_models import (
    OperationRequest,
    OperationResult,
    ProcessingDiagnostic,
    ProcessingRequest,
    ProcessingResult,
    StagedOutputRef,
)
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.pipelines.document_acquisition.result_projection import (
    project_terminal_results,
)
from edgar_sec.pipelines.document_acquisition.schemas import StagedBodyRef

_RUN_ID = "run_projection"
_TARGET_ID = "target_projection"
_ACCESSION = AccessionNumber("0000320193-25-000001")
_BODY = b"fixture filing text\n"
_TARGET_URL = (
    "https://www.sec.gov/Archives/edgar/data/320193/000032019325000001/filing.txt"
)


def _projection_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[AcquisitionPaths, ProcessingRequest, ProcessingResult]:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path / "artifacts")
    staging_root = paths.run_staging_root(_RUN_ID)
    staging_root.mkdir(parents=True, exist_ok=True)
    body_path = staging_root / "source.txt"
    body_path.write_bytes(_BODY)
    digest = hashlib.sha256(_BODY).hexdigest()
    body = StagedBodyRef(
        run_id=_RUN_ID,
        target_id=_TARGET_ID,
        path=body_path,
        sha256=digest,
        byte_size=len(_BODY),
        selected_filename=None,
        source_response_path=body_path,
        source_response_sha256=digest,
        source_response_byte_size=len(_BODY),
    )
    operations = (
        OperationRequest(
            operation_id="op-raw",
            operation="raw",
            requested=True,
            support_status="supported",
            source_request_id="request-raw",
            capability_id="raw",
            capability_version="1",
            handler_id=None,
            handler_version=None,
            output_kind="raw",
        ),
        OperationRequest(
            operation_id="op-text",
            operation="render_to_txt",
            requested=True,
            support_status="supported",
            source_request_id="request-text",
            capability_id="text",
            capability_version="1",
            handler_id="text_passthrough",
            handler_version="1",
            output_kind="text_verbatim",
        ),
        OperationRequest(
            operation_id="op-unsupported",
            operation="render_to_xml",
            requested=True,
            support_status="unsupported",
            source_request_id="request-unsupported",
            capability_id="xml",
            capability_version="1",
            handler_id=None,
            handler_version=None,
            output_kind="xml",
        ),
        OperationRequest(
            operation_id="op-blocked",
            operation="render_to_xml",
            requested=True,
            support_status="not_evaluated",
            source_request_id="request-blocked",
            capability_id=None,
            capability_version=None,
            handler_id=None,
            handler_version=None,
            output_kind="xml",
        ),
        OperationRequest(
            operation_id="op-failed",
            operation="render_to_txt",
            requested=True,
            support_status="supported",
            source_request_id="request-failed",
            capability_id="html-text",
            capability_version="1",
            handler_id="html_to_text",
            handler_version="1",
            output_kind="text",
        ),
        OperationRequest(
            operation_id="op-unrequested",
            operation="render_to_xml",
            requested=False,
            support_status="supported",
            source_request_id="request-unrequested",
            capability_id="xml",
            capability_version="1",
            handler_id=None,
            handler_version=None,
            output_kind="xml",
        ),
    )
    request = ProcessingRequest(
        target_id=_TARGET_ID,
        accession=_ACCESSION,
        form="10-K",
        target_role="primary",
        target_type="primary",
        document_path="filing.txt",
        selected_filename=None,
        source_origin="inventory_index",
        body=body,
        operations=operations,
    )
    processing_id = "proc_fixture"
    statuses = {
        "op-raw": "available",
        "op-text": "available",
        "op-unsupported": "unsupported",
        "op-blocked": "blocked",
        "op-failed": "failed",
        "op-unrequested": "not_requested",
    }
    operation_results = []
    for index, operation in enumerate(operations):
        status = statuses[operation.operation_id]
        available = status == "available"
        output = (
            StagedOutputRef(
                staging_id=processing_id,
                path=body_path,
                representation="raw"
                if operation.operation_id == "op-raw"
                else "text_verbatim",
                output_sha256=digest,
                output_size=len(_BODY),
            )
            if available
            else None
        )
        diagnostic = (
            (ProcessingDiagnostic(f"{status}_fixture", "Synthetic terminal result."),)
            if status in {"unsupported", "blocked", "failed"}
            else ()
        )
        operation_results.append(
            OperationResult(
                operation_id=operation.operation_id,
                operation_fingerprint=hashlib.sha256(
                    operation.operation_id.encode()
                ).hexdigest(),
                status=status,
                representation_id=f"rep_fixture_{index}" if available else None,
                output_sha256=digest if available else None,
                output_size=len(_BODY) if available else None,
                handler_id=operation.handler_id,
                handler_version=operation.handler_version,
                diagnostics=diagnostic,
                staged_output=output,
            )
        )
    result = ProcessingResult(
        processing_id=processing_id,
        target_id=_TARGET_ID,
        source_sha256=digest,
        source_asset_id="asset_fixture",
        route=DocumentRoute.TEXT,
        effective_path="filing.txt",
        operation_results=tuple(operation_results),
    )
    row = {
        "target_id": _TARGET_ID,
        "accession": str(_ACCESSION),
        "form": "10-K",
        "target_role": "primary",
        "target_type": "primary",
        "source_origin": "inventory_index",
        "executable": True,
        "status": "matched",
        "retrieval_mode": "direct_url",
        "target_url": _TARGET_URL,
    }
    monkeypatch.setattr(result_projection, "load_validated_work_order", lambda *_: ())
    monkeypatch.setattr(
        result_projection,
        "iter_work_order_rows",
        lambda _parts: iter((row,)),
    )
    monkeypatch.setattr(
        result_projection,
        "get_staged_body_ref",
        lambda *_: body,
    )
    return paths, request, result


def test_project_terminal_results_preserves_statuses_and_is_deterministic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, request, result = _projection_inputs(tmp_path, monkeypatch)

    with project_terminal_results(
        (item for item in (request,)),
        (item for item in (result,)),
        paths=paths,
        run_id=_RUN_ID,
    ) as first:
        with project_terminal_results(
            (request,),
            (
                replace(
                    result, operation_results=tuple(reversed(result.operation_results))
                ),
            ),
            paths=paths,
            run_id=_RUN_ID,
        ) as second:
            assert first == second
            projected = next(first.iter_targets())
            assert [item.status for item in projected.operations] == [
                "blocked",
                "failed",
                "available",
                "available",
                "not_requested",
                "unsupported",
            ]
            assert projected.source_staged_path == "staging/source.txt"
            assert projected.operations[2].staged_output_path == "staging/source.txt"
            assert first.fingerprint == canonical_hash(
                {
                    "run_id": _RUN_ID,
                    "targets": [projected_target_record(projected)],
                }
            )


def test_projection_spool_is_removed_when_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, request, result = _projection_inputs(tmp_path, monkeypatch)
    projection = project_terminal_results(
        (request,), (result,), paths=paths, run_id=_RUN_ID
    )
    scratch = projection._database_path.parent

    assert scratch.is_dir()
    assert len(tuple(projection.iter_targets())) == 1
    projection.close()

    assert not scratch.exists()
    with pytest.raises(ResultProjectionError, match="spool is closed"):
        next(projection.iter_targets())


def test_project_terminal_results_joins_unordered_streams_and_sorts_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, request, result = _projection_inputs(tmp_path, monkeypatch)
    second_target_id = "target_projection_2"
    second_body = replace(request.body, target_id=second_target_id)
    second_request = replace(request, target_id=second_target_id, body=second_body)
    second_result = replace(
        result,
        target_id=second_target_id,
        processing_id="proc_fixture_2",
        operation_results=tuple(
            replace(
                operation,
                staged_output=(
                    replace(operation.staged_output, staging_id="proc_fixture_2")
                    if operation.staged_output is not None
                    else None
                ),
            )
            for operation in result.operation_results
        ),
    )
    row = {
        "target_id": _TARGET_ID,
        "accession": str(_ACCESSION),
        "form": "10-K",
        "target_role": "primary",
        "target_type": "primary",
        "source_origin": "inventory_index",
        "executable": True,
        "status": "matched",
        "retrieval_mode": "direct_url",
        "target_url": _TARGET_URL,
    }
    monkeypatch.setattr(
        result_projection,
        "iter_work_order_rows",
        lambda _parts: iter((row, {**row, "target_id": second_target_id})),
    )
    monkeypatch.setattr(
        result_projection,
        "get_staged_body_ref",
        lambda _paths, _run_id, target_id: (
            request.body if target_id == _TARGET_ID else second_body
        ),
    )

    with project_terminal_results(
        (second_request, request),
        (result, second_result),
        paths=paths,
        run_id=_RUN_ID,
    ) as projection:
        assert [target.target_id for target in projection.iter_targets()] == [
            _TARGET_ID,
            second_target_id,
        ]


def test_project_terminal_results_rejects_missing_target_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, request, _result = _projection_inputs(tmp_path, monkeypatch)

    with pytest.raises(ResultProjectionError, match="coverage is incomplete"):
        project_terminal_results((request,), (), paths=paths, run_id=_RUN_ID)


def test_project_terminal_results_rejects_duplicate_targets_and_operations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, request, result = _projection_inputs(tmp_path, monkeypatch)

    with pytest.raises(ResultProjectionError, match="request target is duplicated"):
        project_terminal_results(
            (request, request), (result,), paths=paths, run_id=_RUN_ID
        )
    with pytest.raises(ResultProjectionError, match="result target is duplicated"):
        project_terminal_results(
            (request,), (result, result), paths=paths, run_id=_RUN_ID
        )
    duplicate = replace(
        result,
        operation_results=(
            result.operation_results[0],
            result.operation_results[0],
            *result.operation_results[1:],
        ),
    )
    with pytest.raises(
        ResultProjectionError, match="operation result ID is duplicated"
    ):
        project_terminal_results((request,), (duplicate,), paths=paths, run_id=_RUN_ID)
    incomplete = replace(result, operation_results=result.operation_results[:-1])
    with pytest.raises(
        ResultProjectionError, match="operation result set is incomplete"
    ):
        project_terminal_results((request,), (incomplete,), paths=paths, run_id=_RUN_ID)


def test_project_terminal_results_rejects_pending_operation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, request, result = _projection_inputs(tmp_path, monkeypatch)
    pending = replace(result.operation_results[0], status="pending")
    result = replace(result, operation_results=(pending, *result.operation_results[1:]))

    with pytest.raises(ResultProjectionError, match="not terminal"):
        project_terminal_results((request,), (result,), paths=paths, run_id=_RUN_ID)


def test_project_terminal_results_rejects_staged_output_digest_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, request, result = _projection_inputs(tmp_path, monkeypatch)
    wrong = replace(result.operation_results[0], output_sha256="0" * 64)
    result = replace(result, operation_results=(wrong, *result.operation_results[1:]))

    with pytest.raises(ResultProjectionError, match="staged output differs"):
        project_terminal_results((request,), (result,), paths=paths, run_id=_RUN_ID)


def test_project_terminal_results_rejects_output_outside_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, request, result = _projection_inputs(tmp_path, monkeypatch)
    outside = tmp_path / "outside.txt"
    outside.write_bytes(_BODY)
    output = replace(result.operation_results[0].staged_output, path=outside)
    operation = replace(result.operation_results[0], staged_output=output)
    result = replace(
        result, operation_results=(operation, *result.operation_results[1:])
    )

    with pytest.raises(ResultProjectionError, match="escapes the run staging root"):
        project_terminal_results((request,), (result,), paths=paths, run_id=_RUN_ID)


def test_project_terminal_results_rejects_work_order_identity_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, request, result = _projection_inputs(tmp_path, monkeypatch)

    with pytest.raises(ResultProjectionError, match="differs from work order"):
        project_terminal_results(
            (replace(request, form="8-K"),), (result,), paths=paths, run_id=_RUN_ID
        )


def test_project_terminal_results_refuses_bundle_without_s9_filename_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, request, result = _projection_inputs(tmp_path, monkeypatch)

    def bundle_target(_parts: tuple[Path, ...]):
        yield {**_work_order_row(), "retrieval_mode": "bundle_sequence"}

    def _work_order_row():
        return {
            "target_id": _TARGET_ID,
            "accession": str(_ACCESSION),
            "form": "10-K",
            "target_role": "primary",
            "target_type": "primary",
            "source_origin": "inventory_index",
            "executable": True,
            "status": "matched",
            "retrieval_mode": "direct_url",
            "target_url": _TARGET_URL,
        }

    monkeypatch.setattr(result_projection, "iter_work_order_rows", bundle_target)

    with pytest.raises(ResultProjectionError, match="selected-filename evidence"):
        project_terminal_results((request,), (result,), paths=paths, run_id=_RUN_ID)
