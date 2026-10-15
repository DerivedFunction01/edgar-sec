from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from edgar_sec.domain.document.route import DocumentRoute
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.pipelines.document_acquisition.processing.io import (
    DEFAULT_PROCESSING_BUDGETS,
    ProcessingBudgetExceeded,
    ProcessingBudgetPolicy,
    ProcessingBudgetRegistry,
    ProcessingIOError,
    admit_processing_budget,
    read_bounded_source,
    stage_derived_output,
)


def test_route_handler_budget_bounds_input_and_working_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import edgar_sec.pipelines.document_acquisition.processing.io as processing_io

    source = b"verified source"
    path = tmp_path / "selected.bin"
    path.write_bytes(source)
    monkeypatch.setattr(
        processing_io,
        "available_memory_bytes",
        lambda: 256,
    )
    policy = ProcessingBudgetPolicy(
        budget_version="test-v1",
        route=DocumentRoute.TEXT,
        handler_id="normalize_document",
        handler_version="1",
        max_input_bytes=64,
        max_output_bytes=64,
        working_set_reservation_bytes=16,
    )
    registry = ProcessingBudgetRegistry((policy,))

    assert registry.get(DocumentRoute.TEXT, "normalize_document", "1") == policy
    assert DEFAULT_PROCESSING_BUDGETS.policies == ()
    assert admit_processing_budget(policy, len(source))
    assert not admit_processing_budget(policy, policy.max_input_bytes + 1)
    assert not admit_processing_budget(policy, len(source), available_bytes=32)

    assert (
        read_bounded_source(path, len(source), max_input_bytes=policy.max_input_bytes)
        == source
    )
    with pytest.raises(ProcessingBudgetExceeded, match="input budget"):
        read_bounded_source(path, len(source), max_input_bytes=len(source) - 1)


def test_derived_output_stages_atomically_with_verified_identity(
    tmp_path: Path,
) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path / "artifacts")
    output = b"normalized output"
    digest = hashlib.sha256(output).hexdigest()
    staged = stage_derived_output(
        paths,
        run_id="run_test",
        processing_id="proc_test",
        operation_id="operation-test",
        representation="text_normalized",
        output=output,
        expected_sha256=digest,
        expected_size=len(output),
    )

    assert staged.path.is_relative_to(paths.run_staging_root("run_test"))
    assert staged.path.read_bytes() == output
    assert staged.output_sha256 == digest
    assert staged.output_size == len(output)

    with pytest.raises(ProcessingIOError, match="metadata is invalid"):
        stage_derived_output(
            paths,
            run_id="run_test",
            processing_id="proc_test",
            operation_id="other-operation",
            representation="text_normalized",
            output=output,
            expected_sha256="0" * 64,
            expected_size=len(output),
        )


def test_production_processing_budgets_registers_standard_handlers() -> None:
    from edgar_sec.pipelines.document_acquisition.processing.io import (
        production_processing_budgets,
    )

    budgets = production_processing_budgets()
    assert len(budgets.policies) == 9

    norm_markup = budgets.get(DocumentRoute.MARKUP, "normalize_document", "1")
    assert norm_markup is not None
    assert norm_markup.max_input_bytes == 67_108_864

    norm_text = budgets.get(DocumentRoute.TEXT, "normalize_document", "1")
    assert norm_text is not None

    form4_xml = budgets.get(DocumentRoute.XML, "form4_html_to_xml", "1")
    assert form4_xml is not None
    assert form4_xml.max_input_bytes == 16_777_216

    form4_markup = budgets.get(DocumentRoute.MARKUP, "form4_html_to_xml", "1")
    assert form4_markup is not None
