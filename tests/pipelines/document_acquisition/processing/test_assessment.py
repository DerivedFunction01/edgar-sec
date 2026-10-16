from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from edgar_sec.domain.document.route import DocumentRoute
from edgar_sec.pipelines.document_acquisition.processing.assessment import (
    assess_exhibit_processing,
)
from edgar_sec.pipelines.document_acquisition.processing.models import (
    OperationResult,
    StagedOutputRef,
)
from edgar_sec.pipelines.document_acquisition.processing.worker import process_target
from tests.support import (
    minimal_processing_request,
    stub_processing_target_validation,
)


def _text_result(path: Path, operation_id: str, text: str) -> OperationResult:
    payload = text.encode("utf-8")
    path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    return OperationResult(
        operation_id=operation_id,
        operation_fingerprint="a" * 64,
        status="available",
        representation_id="rep_text",
        output_sha256=digest,
        output_size=len(payload),
        handler_id="normalize_document",
        handler_version="1",
        diagnostics=(),
        staged_output=StagedOutputRef(
            staging_id="processing_test",
            path=path,
            representation="text_normalized",
            output_sha256=digest,
            output_size=len(payload),
        ),
    )


def test_assessment_is_bounded_pinned_and_non_authoritative(tmp_path: Path) -> None:
    paths, original = minimal_processing_request(tmp_path)
    request = replace(original, target_role="exhibit", target_type="EX-3.1")
    text_operation = next(
        operation
        for operation in request.operations
        if operation.operation == "render_to_txt"
    )
    result = _text_result(
        paths.run_staging_root(request.body.run_id) / "normalized.txt",
        text_operation.operation_id,
        "EXHIBIT 3.1\nARTICLES OF INCORPORATION\n",
    )

    assessment, fingerprint = assess_exhibit_processing(
        request, (result,), DocumentRoute.TEXT, "filing.txt"
    )

    assert assessment is not None
    assert assessment.disposition == "consistent"
    assert assessment.pack_id == "ex3_1"
    assert fingerprint is not None and len(fingerprint) == 64
    assert result.status == "available"
    assert request.target_type == "EX-3.1"


def test_processing_attaches_diagnostic_without_changing_operation_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import edgar_sec.engine.forms.normalize as normalizer
    import edgar_sec.pipelines.document_acquisition.processing.io as processing_io
    import edgar_sec.pipelines.document_acquisition.processing.worker as processing

    paths, original = minimal_processing_request(tmp_path)
    request = replace(original, target_role="exhibit", target_type="EX-3.1")
    stub_processing_target_validation(monkeypatch, request)
    monkeypatch.setattr(
        normalizer,
        "normalize_document",
        lambda *_args, **_kwargs: SimpleNamespace(
            text="EXHIBIT 3.1\nARTICLES OF INCORPORATION\n"
        ),
    )
    monkeypatch.setattr(
        processing, "get_staged_body_metadata_ref", lambda *_args: request.body
    )
    monkeypatch.setattr(processing, "_record_receipt", lambda *_args: None)

    result = process_target(request, paths=paths)

    assert result.exhibit_assessment is not None
    assert result.exhibit_assessment.disposition == "consistent"
    assert result.exhibit_assessment_fingerprint is not None
    assert [item.status for item in result.operation_results] == [
        "available",
        "available",
        "not_requested",
    ]
