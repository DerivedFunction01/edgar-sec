from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from edgar_sec.domain.document.route import DocumentRoute
from edgar_sec.pipelines.document_acquisition.processing.worker import (
    ProcessingError,
    process_target,
)
from edgar_sec.pipelines.document_acquisition.processing.io import (
    ProcessingBudgetRegistry,
)
from tests.support import (
    PROCESSING_TEST_BODY as _BODY,
    acquired_processing_request as _acquired_request,
    failed_processing_operation_result,
    minimal_processing_request as _minimal_request,
    processing_body_receipt as _processing_body_receipt,
    processing_budget_registry as _budget_registry,
    stub_processing_target_validation as _stub_target_validation,
    two_text_processing_operations as _two_text_operations,
)


def test_process_target_returns_deterministic_identity_results_and_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, request = _minimal_request(tmp_path)
    _stub_target_validation(monkeypatch, request)
    calls = []

    def normalize(raw_bytes: bytes, **kwargs: object) -> SimpleNamespace:
        calls.append((raw_bytes, kwargs["document_path"], kwargs["content_route"]))
        return SimpleNamespace(text="normalized filing text")

    import edgar_sec.engine.forms.normalize as normalizer
    import edgar_sec.pipelines.document_acquisition.processing.worker as processing
    import edgar_sec.pipelines.document_acquisition.processing.io as processing_io

    monkeypatch.setattr(normalizer, "normalize_document", normalize)
    monkeypatch.setattr(processing_io, "available_memory_bytes", lambda: 4096)
    monkeypatch.setattr(
        processing,
        "get_staged_body_metadata_ref",
        lambda *_args: request.body,
    )
    receipt_calls = []
    monkeypatch.setattr(
        processing,
        "_record_receipt",
        lambda *_args: receipt_calls.append(True),
    )

    first = process_target(request, paths=paths, budget_registry=_budget_registry())
    second = process_target(request, paths=paths, budget_registry=_budget_registry())

    assert first == second
    assert first.route.value == "text"
    assert first.source_sha256 == request.body.sha256
    assert [item.status for item in first.operation_results] == [
        "available",
        "available",
        "not_requested",
    ]
    assert first.operation_results[0].staged_output.path == request.body.path
    derived = first.operation_results[1].staged_output
    assert derived is not None
    assert derived.path != request.body.path
    assert derived.representation == "text_normalized"
    assert derived.path.read_bytes() == b"normalized filing text"
    assert (
        derived.output_sha256 == hashlib.sha256(derived.path.read_bytes()).hexdigest()
    )
    assert derived.output_size == derived.path.stat().st_size
    assert calls == [
        (_BODY, request.document_path, "text"),
        (_BODY, request.document_path, "text"),
    ]
    assert receipt_calls == [True, True]
    assert request.body.path.read_bytes() == _BODY
    assert first.operation_results[2].staged_output is None


def test_retry_reuses_prior_success_and_executes_only_selected_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import edgar_sec.engine.forms.normalize as normalizer
    import edgar_sec.pipelines.document_acquisition.processing.worker as processing
    import edgar_sec.pipelines.document_acquisition.processing.io as processing_io

    paths, request = _minimal_request(tmp_path)
    request = _two_text_operations(request)
    _stub_target_validation(monkeypatch, request)
    monkeypatch.setattr(processing_io, "available_memory_bytes", lambda: 4096)
    monkeypatch.setattr(
        processing, "get_staged_body_metadata_ref", lambda *_args: request.body
    )
    receipt_calls = []
    monkeypatch.setattr(
        processing,
        "_record_receipt",
        lambda *_args: receipt_calls.append(_args[2]),
    )
    handler_calls = []

    def normalize(*_args: object, **_kwargs: object) -> SimpleNamespace:
        handler_calls.append(len(handler_calls) + 1)
        if len(handler_calls) > 1:
            raise RuntimeError("retryable handler error")
        return SimpleNamespace(text="first output")

    monkeypatch.setattr(normalizer, "normalize_document", normalize)
    initial = process_target(request, paths=paths, budget_registry=_budget_registry())

    assert [result.status for result in initial.operation_results] == [
        "available",
        "available",
        "failed",
    ]
    first_raw, first_success, first_failure = initial.operation_results
    assert first_failure.operation_id == "text-retry"
    assert handler_calls == [1, 2]

    retried = process_target(
        request,
        paths=paths,
        budget_registry=_budget_registry(),
        prior_results=(first_raw, first_success),
        selected_operation_ids=("text-retry",),
    )

    assert retried.processing_id == initial.processing_id
    assert retried.operation_results[0] is first_raw
    assert retried.operation_results[1] is first_success
    assert retried.operation_results[2].operation_id == first_failure.operation_id
    assert retried.operation_results[2].status == "failed"
    assert handler_calls == [1, 2, 3]
    assert receipt_calls == [initial.processing_id, initial.processing_id]


def test_reused_results_skip_memory_admission_for_unselected_operations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import edgar_sec.engine.forms.normalize as normalizer
    import edgar_sec.pipelines.document_acquisition.processing.worker as processing
    import edgar_sec.pipelines.document_acquisition.processing.io as processing_io

    paths, request = _minimal_request(tmp_path)
    _stub_target_validation(monkeypatch, request)
    monkeypatch.setattr(processing_io, "available_memory_bytes", lambda: 4096)
    monkeypatch.setattr(
        processing, "get_staged_body_metadata_ref", lambda *_args: request.body
    )
    receipt_calls = []
    monkeypatch.setattr(
        processing,
        "_record_receipt",
        lambda *_args: receipt_calls.append(True),
    )
    handler_calls = []
    monkeypatch.setattr(
        normalizer,
        "normalize_document",
        lambda *_args, **_kwargs: (
            handler_calls.append(True) or SimpleNamespace(text="completed")
        ),
    )
    initial = process_target(request, paths=paths, budget_registry=_budget_registry())
    monkeypatch.setattr(
        processing_io,
        "available_memory_bytes",
        lambda: pytest.fail("reused operations must not be re-admitted"),
    )
    monkeypatch.setattr(
        processing,
        "read_bounded_source",
        lambda *_args, **_kwargs: pytest.fail("reused operations must not read body"),
    )
    monkeypatch.setattr(
        processing,
        "get_staged_body_ref",
        lambda *_args: pytest.fail("reused raw result must not re-hash body"),
    )

    reused = process_target(
        request,
        paths=paths,
        budget_registry=_budget_registry(),
        prior_results=initial.operation_results[:2],
        selected_operation_ids=(),
    )

    assert reused.processing_id == initial.processing_id
    assert reused.operation_results[:2] == initial.operation_results[:2]
    assert reused.operation_results[0] is initial.operation_results[0]
    assert reused.operation_results[1] is initial.operation_results[1]
    assert handler_calls == [True]
    assert receipt_calls == [True]


@pytest.mark.parametrize(
    "stale_kind",
    ["fingerprint", "output", "raw_path", "raw_digest", "raw_size", "source", "budget"],
)
def test_retry_rejects_stale_prior_fingerprint_or_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stale_kind: str,
) -> None:
    import edgar_sec.engine.document_processing.processor as engine_processor
    import edgar_sec.engine.forms.normalize as normalizer
    import edgar_sec.pipelines.document_acquisition.processing.worker as processing
    import edgar_sec.pipelines.document_acquisition.processing.io as processing_io

    paths, request = _minimal_request(tmp_path)
    _stub_target_validation(monkeypatch, request)
    registry = _budget_registry()
    monkeypatch.setattr(processing_io, "available_memory_bytes", lambda: 4096)
    monkeypatch.setattr(
        processing, "get_staged_body_metadata_ref", lambda *_args: request.body
    )
    monkeypatch.setattr(processing, "_record_receipt", lambda *_args: None)
    monkeypatch.setattr(
        normalizer,
        "normalize_document",
        lambda *_args, **_kwargs: SimpleNamespace(text="completed"),
    )
    completed = process_target(request, paths=paths, budget_registry=registry)
    prior = completed.operation_results
    replay_request = request
    replay_registry = registry

    if stale_kind == "fingerprint":
        prior = (
            prior[0],
            replace(prior[1], operation_fingerprint="0" * 64),
        )
    elif stale_kind == "output":
        staged = replace(prior[1].staged_output, output_size=prior[1].output_size + 1)
        prior = (prior[0], replace(prior[1], staged_output=staged))
    elif stale_kind.startswith("raw_"):
        staged = prior[0].staged_output
        if stale_kind == "raw_path":
            staged = replace(staged, path=request.body.path.parent / "other-body.bin")
        elif stale_kind == "raw_digest":
            staged = replace(staged, output_sha256="0" * 64)
        else:
            staged = replace(staged, output_size=staged.output_size + 1)
        prior = (replace(prior[0], staged_output=staged), prior[1])
    elif stale_kind == "source":
        replay_request = replace(
            request,
            operations=(
                request.operations[0],
                replace(request.operations[1], source_request_id="other-source"),
                request.operations[2],
            ),
        )
        _stub_target_validation(monkeypatch, replay_request)
        monkeypatch.setattr(
            processing,
            "get_staged_body_metadata_ref",
            lambda *_args: replay_request.body,
        )
    elif stale_kind == "budget":
        replay_registry = _budget_registry(budget_version="test-v2")

    monkeypatch.setattr(
        processing_io,
        "available_memory_bytes",
        lambda: pytest.fail("no selected operation should be admitted"),
    )
    monkeypatch.setattr(
        processing,
        "read_bounded_source",
        lambda *_args, **_kwargs: pytest.fail(
            "stale prior must refuse before body read"
        ),
    )
    monkeypatch.setattr(
        processing,
        "get_staged_body_ref",
        lambda *_args: pytest.fail("stale prior must not re-hash body"),
    )

    with pytest.raises(ProcessingError):
        process_target(
            replay_request,
            paths=paths,
            budget_registry=replay_registry,
            prior_results=prior[:2],
            selected_operation_ids=(),
        )


def test_retry_requires_coverage(tmp_path: Path) -> None:
    paths, request = _minimal_request(tmp_path)

    with pytest.raises(ProcessingError):
        process_target(
            request,
            paths=paths,
            selected_operation_ids=("raw-test",),
        )


@pytest.mark.parametrize(
    "invalid_case",
    ["duplicate_prior", "unknown_prior", "unknown_selected", "unsupported_selected"],
)
def test_retry_rejects_invalid_ids(
    tmp_path: Path,
    invalid_case: str,
) -> None:
    paths, request = _minimal_request(tmp_path)
    prior = failed_processing_operation_result(
        "raw-test" if invalid_case == "duplicate_prior" else "unknown-op"
    )
    kwargs = {}
    if invalid_case == "duplicate_prior":
        kwargs["prior_results"] = (prior, prior)
    elif invalid_case == "unknown_prior":
        kwargs["prior_results"] = (prior,)
    elif invalid_case == "unknown_selected":
        kwargs["selected_operation_ids"] = ("unknown-op",)
    else:
        kwargs["selected_operation_ids"] = ("xml-test",)

    with pytest.raises(ProcessingError):
        process_target(request, paths=paths, **kwargs)


def test_process_target_records_receipt_when_export_handler_is_missing(
    tmp_path: Path,
) -> None:
    paths, request = _acquired_request(tmp_path)
    operation = replace(
        request.operations[1],
        handler_id="missing-text-handler",
        handler_version="1",
    )
    request = replace(request, operations=(request.operations[0], operation))

    result = process_target(request, paths=paths)

    assert result.operation_results[0].status == "available"
    assert result.operation_results[0].staged_output.path == request.body.path
    assert result.operation_results[1].status == "failed"
    assert result.operation_results[1].diagnostics[0].code == "capability_pin_mismatch"
    assert result.operation_results[1].staged_output is None
    assert request.body.path.read_bytes() == _BODY
    assert _processing_body_receipt(paths, request.body)


def test_process_target_uses_lazy_direct_selection_evidence_for_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, request = _acquired_request(tmp_path, lazy_selected=True)
    request = replace(
        request,
        operations=(
            request.operations[0],
            replace(request.operations[1], capability_id="text.markup"),
            request.operations[2],
        ),
    )
    import edgar_sec.pipelines.document_acquisition.processing.io as processing_io

    monkeypatch.setattr(processing_io, "available_memory_bytes", lambda: 4096)

    result = process_target(
        request,
        paths=paths,
        budget_registry=_budget_registry(DocumentRoute.MARKUP),
    )

    assert result.route.value == "markup"
    assert result.effective_path == "report.htm"
    assert result.operation_results[0].status == "available"
    assert result.operation_results[1].status == "available"
    assert result.operation_results[1].staged_output.path != request.body.path
    assert result.operation_results[2].status == "not_requested"


def test_process_target_rejects_route_pin_that_conflicts_with_lazy_selection(
    tmp_path: Path,
) -> None:
    paths, request = _acquired_request(tmp_path, lazy_selected=True)
    original_body = request.body.path.read_bytes()

    result = process_target(request, paths=paths)

    assert result.effective_path == "report.htm"
    assert result.operation_results[0].status == "available"
    assert result.operation_results[1].status == "failed"
    assert result.operation_results[1].diagnostics[0].code == "capability_pin_mismatch"
    assert result.operation_results[1].staged_output is None
    assert request.body.path.read_bytes() == original_body


def test_process_target_keeps_raw_when_normalization_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, request = _acquired_request(tmp_path)

    def fail_normalize(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("fixture handler failure")

    import edgar_sec.engine.forms.normalize as normalizer
    import edgar_sec.pipelines.document_acquisition.processing.io as processing_io

    monkeypatch.setattr(normalizer, "normalize_document", fail_normalize)
    monkeypatch.setattr(processing_io, "available_memory_bytes", lambda: 4096)
    result = process_target(request, paths=paths, budget_registry=_budget_registry())

    assert result.operation_results[0].status == "available"
    assert result.operation_results[1].status == "failed"
    assert result.operation_results[1].staged_output is None
    assert request.body.path.read_bytes() == _BODY
    assert _processing_body_receipt(paths, request.body)


def test_admitted_transform_hashes_selected_bytes_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import edgar_sec.engine.document_processing.processor as engine_processor
    import edgar_sec.engine.forms.normalize as normalizer
    import edgar_sec.pipelines.document_acquisition.body_handoff as body_handoff
    import edgar_sec.pipelines.document_acquisition.processing.worker as processing
    import edgar_sec.pipelines.document_acquisition.processing.io as processing_io

    paths, request = _minimal_request(tmp_path)
    _stub_target_validation(monkeypatch, request)
    monkeypatch.setattr(
        normalizer,
        "normalize_document",
        lambda *_args, **_kwargs: SimpleNamespace(text="admitted text"),
    )
    monkeypatch.setattr(processing_io, "available_memory_bytes", lambda: 4096)
    metadata_refs = []
    monkeypatch.setattr(
        processing,
        "get_staged_body_metadata_ref",
        lambda *_args: metadata_refs.append(request.body) or request.body,
    )
    monkeypatch.setattr(
        processing,
        "get_staged_body_ref",
        lambda *_args: pytest.fail("admitted transform rehashed via body handoff"),
    )
    receipt_calls = []
    monkeypatch.setattr(
        processing,
        "_record_receipt",
        lambda *_args: receipt_calls.append(True),
    )
    monkeypatch.setattr(
        body_handoff,
        "_hash_file",
        lambda *_args, **_kwargs: pytest.fail("admitted path must not hash twice"),
    )
    original_hash = engine_processor.sha256_bytes
    selected_hashes = []

    def count_selected_hash(raw_bytes: bytes) -> str:
        if raw_bytes == _BODY:
            selected_hashes.append(raw_bytes)
        return original_hash(raw_bytes)

    monkeypatch.setattr(engine_processor, "sha256_bytes", count_selected_hash)
    result = process_target(request, paths=paths, budget_registry=_budget_registry())

    assert selected_hashes == [_BODY]
    assert metadata_refs == [request.body]
    assert receipt_calls == [True]
    assert result.operation_results[0].status == "available"
    assert result.operation_results[1].status == "available"


def test_process_target_requires_pinned_raw_for_matched_target(tmp_path: Path) -> None:
    paths, request = _acquired_request(tmp_path)
    request = replace(request, operations=request.operations[1:])

    with pytest.raises(ProcessingError, match="mandatory pinned raw"):
        process_target(request, paths=paths)
    assert request.body.path.read_bytes() == _BODY
    assert _processing_body_receipt(paths, request.body) is None


@pytest.mark.parametrize("budgeted", [False, True])
def test_unbudgeted_or_oversized_text_fails_before_body_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, budgeted: bool
) -> None:
    import edgar_sec.pipelines.document_acquisition.body_handoff as body_handoff
    import edgar_sec.pipelines.document_acquisition.processing.worker as processing
    import edgar_sec.pipelines.document_acquisition.processing.io as processing_io

    paths, request = _minimal_request(tmp_path)
    _stub_target_validation(monkeypatch, request)
    original_body = request.body.path.read_bytes()
    if budgeted:
        registry = _budget_registry(max_input_bytes=1, max_output_bytes=16)
        monkeypatch.setattr(processing_io, "available_memory_bytes", lambda: 4096)
    else:
        registry = ProcessingBudgetRegistry()

    hashed = []
    opened = []
    receipts = []
    metadata_refs = []

    def unexpected_hash(*args: object, **_kwargs: object) -> None:
        hashed.append(args)
        raise AssertionError("selected body must not be hashed before admission")

    def unexpected_read(*args: object, **_kwargs: object) -> None:
        opened.append(args)
        raise AssertionError("selected body must not be read before admission")

    def unexpected_receipt(*args: object, **_kwargs: object) -> None:
        receipts.append(args)
        raise AssertionError("budget rejection must not record a receipt")

    monkeypatch.setattr(body_handoff, "_hash_file", unexpected_hash)
    monkeypatch.setattr(processing_io.os, "open", unexpected_read)
    monkeypatch.setattr(processing, "read_bounded_source", unexpected_read)
    monkeypatch.setattr(
        processing,
        "get_staged_body_ref",
        lambda *_args: pytest.fail("budget refusal used byte-verifying handoff"),
    )
    monkeypatch.setattr(
        processing,
        "get_staged_body_metadata_ref",
        lambda *_args: metadata_refs.append(request.body) or request.body,
    )
    monkeypatch.setattr(
        processing, "record_body_consumption_receipt", unexpected_receipt
    )

    result = process_target(request, paths=paths, budget_registry=registry)

    assert result.operation_results[0].status == "available"
    assert result.operation_results[1].status == "blocked"
    assert (
        result.operation_results[1].diagnostics[0].code == "processing_budget_exceeded"
    )
    assert result.operation_results[0].staged_output.path == request.body.path
    assert result.operation_results[0].output_sha256 == request.body.sha256
    assert result.operation_results[0].output_size == request.body.byte_size
    assert result.operation_results[1].staged_output is None
    assert hashed == opened == receipts == []
    assert metadata_refs == [request.body]
    assert request.body.path.read_bytes() == original_body


def test_raw_only_processing_is_file_backed_and_skips_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import edgar_sec.pipelines.document_acquisition.processing.worker as processing

    paths, request = _minimal_request(tmp_path)
    _stub_target_validation(monkeypatch, request)
    request = replace(request, operations=request.operations[:1])

    def forbidden_materialization(*_args: object, **_kwargs: object) -> bytes:
        raise AssertionError("raw identity must not materialize the selected body")

    def forbidden_engine(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("raw identity must not invoke the processing engine")

    monkeypatch.setattr(processing, "read_bounded_source", forbidden_materialization)
    monkeypatch.setattr(processing.AcquisitionProcessor, "process", forbidden_engine)
    metadata_refs = []
    verified_refs = []
    receipt_calls = []
    monkeypatch.setattr(
        processing,
        "get_staged_body_metadata_ref",
        lambda *_args: metadata_refs.append(request.body) or request.body,
    )
    monkeypatch.setattr(
        processing,
        "get_staged_body_ref",
        lambda *_args: verified_refs.append(request.body) or request.body,
    )
    monkeypatch.setattr(
        processing, "_record_receipt", lambda *_args: receipt_calls.append(True)
    )
    result = process_target(request, paths=paths)

    raw = result.operation_results[0]
    assert raw.status == "available"
    assert raw.staged_output is not None
    assert raw.staged_output.path == request.body.path
    assert request.body.path.read_bytes() == _BODY
    assert metadata_refs == verified_refs == [request.body]
    assert receipt_calls == [True]


def test_unsupported_xml_does_not_block_raw_only_processing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import edgar_sec.pipelines.document_acquisition.processing.worker as processing

    paths, request = _minimal_request(tmp_path)
    _stub_target_validation(monkeypatch, request)
    xml = replace(
        request.operations[2],
        requested=True,
        support_status="unsupported",
        capability_id=None,
        capability_version=None,
        handler_id=None,
        handler_version=None,
        output_kind=None,
    )
    request = replace(request, operations=(request.operations[0], xml))
    monkeypatch.setattr(
        processing.AcquisitionProcessor,
        "process",
        lambda *_args, **_kwargs: pytest.fail("unsupported XML reached the engine"),
    )
    monkeypatch.setattr(
        processing, "get_staged_body_metadata_ref", lambda *_args: request.body
    )
    monkeypatch.setattr(processing, "get_staged_body_ref", lambda *_args: request.body)
    monkeypatch.setattr(processing, "_record_receipt", lambda *_args: None)

    result = process_target(request, paths=paths)

    assert result.operation_results[0].status == "available"
    assert result.operation_results[0].staged_output.path == request.body.path
    assert result.operation_results[1].status == "unsupported"


def test_output_above_registered_limit_is_not_staged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import edgar_sec.engine.forms.normalize as normalizer
    import edgar_sec.pipelines.document_acquisition.processing.worker as processing
    import edgar_sec.pipelines.document_acquisition.processing.io as processing_io

    paths, request = _minimal_request(tmp_path)
    _stub_target_validation(monkeypatch, request)
    monkeypatch.setattr(
        normalizer,
        "normalize_document",
        lambda *_args, **_kwargs: SimpleNamespace(text="x" * 32),
    )
    monkeypatch.setattr(processing_io, "available_memory_bytes", lambda: 4096)
    monkeypatch.setattr(
        processing,
        "get_staged_body_metadata_ref",
        lambda *_args: request.body,
    )
    receipt_calls = []
    monkeypatch.setattr(
        processing, "_record_receipt", lambda *_args: receipt_calls.append(True)
    )

    result = process_target(
        request,
        paths=paths,
        budget_registry=_budget_registry(max_output_bytes=16),
    )

    raw, text = result.operation_results[:2]
    assert raw.status == "available"
    assert text.status == "failed"
    assert text.diagnostics[0].code == "processing_budget_exceeded"
    assert text.staged_output is None
    assert not (paths.run_staging_root(request.body.run_id) / "processing").exists()
    assert receipt_calls == []


def test_form4_xml_without_registered_handler_is_unsupported(
    tmp_path: Path,
) -> None:
    from edgar_sec.domain.document.path_facts import DocumentPathFacts
    from edgar_sec.pipelines.document_acquisition.processing.worker import (
        _operation_results,
    )

    paths, request = _minimal_request(tmp_path)
    raw, _, _ = request.operations
    xml = replace(
        request.operations[2],
        operation_id="form4-xml",
        operation="render_to_xml",
        requested=True,
        support_status="supported",
        capability_id="form4.htm.render_to_xml",
        capability_version="v1",
        handler_id="form4_html_to_xml",
        handler_version="1",
        output_kind="xml",
    )
    request = replace(request, form="4", operations=(raw, xml))
    effective_path = "report.htm"
    body = request.body.path.read_bytes()
    processing_id = "proc_form4_xml_test"
    results = _operation_results(
        request,
        paths,
        DocumentRoute.MARKUP,
        effective_path,
        DocumentPathFacts.from_archive_path(effective_path),
        request.body,
        body,
        processing_id,
        {},
        {},
        {},
        {},
        frozenset({raw.operation_id, xml.operation_id}),
    )

    assert results[0].status == "available"
    assert results[0].staged_output.path == request.body.path
    assert results[1].status == "unsupported"
    assert results[1].diagnostics[0].code == "route_unsupported"
    assert results[1].staged_output is None
    assert request.body.path.read_bytes() == body


def test_process_target_rejects_selected_filename_for_direct_target(
    tmp_path: Path,
) -> None:
    paths, request = _acquired_request(tmp_path, selected_filename="report.html")

    with pytest.raises(
        ProcessingError,
        match="direct target has an unexpected selected filename",
    ):
        process_target(request, paths=paths)

    assert _processing_body_receipt(paths, request.body) is None


def test_process_target_refuses_mismatched_work_order_identity_without_receipt(
    tmp_path: Path,
) -> None:
    paths, request = _acquired_request(tmp_path)

    with pytest.raises(ProcessingError, match="differs from work order"):
        process_target(replace(request, form="8-K"), paths=paths)

    assert _processing_body_receipt(paths, request.body) is None


def test_process_target_refuses_changed_staged_body_without_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, request = _acquired_request(tmp_path)
    request.body.path.write_bytes(b"changed")
    import edgar_sec.pipelines.document_acquisition.processing.io as processing_io

    monkeypatch.setattr(processing_io, "available_memory_bytes", lambda: 4096)

    with pytest.raises(ProcessingError):
        process_target(request, paths=paths, budget_registry=_budget_registry())

    assert _processing_body_receipt(paths, request.body) is None


def test_process_target_refuses_bundle_without_committed_child_filename(
    tmp_path: Path,
) -> None:
    paths, request = _acquired_request(tmp_path)
    from edgar_sec.pipelines.document_acquisition.processing.worker import (
        _effective_route,
    )

    with pytest.raises(ProcessingError, match="bundle child filename"):
        _effective_route(
            paths,
            request,
            {"retrieval_mode": "bundle_sequence", "_document_path": "filing.txt"},
            request.body,
        )

    assert _processing_body_receipt(paths, request.body) is None
