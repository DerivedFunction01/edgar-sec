"""Tests for deterministic acquisition operation execution."""

from __future__ import annotations

import pytest

from edgar_sec.domain.document.path_facts import (
    DocumentPathFacts,
    DocumentPathShape,
    DocumentSuffixClass,
)
from edgar_sec.domain.document.route import DocumentRoute
from edgar_sec.engine.document_processing.capabilities import (
    DEFAULT_CAPABILITIES,
    HandlerOutputKind,
    ProcessingCapability,
    ProcessingCapabilityRegistry,
)
from edgar_sec.engine.document_processing.processor import (
    AcquisitionProcessRequest,
    AcquisitionProcessor,
    InputRecord,
    OperationRecord,
)
from edgar_sec.engine.document_processing.outputs import HandlerOutput, HandlerSidecar
from edgar_sec.engine.document_processing.registry import HandlerRegistry
from edgar_sec.foundation.hashing import sha256_bytes


def _path_facts(path: str) -> DocumentPathFacts:
    return DocumentPathFacts.from_archive_path(path)


def _input(
    source_id: str = "source",
    path: str = "document.html",
    body: bytes = b"<html><body><p>Filed text.</p></body></html>",
    *,
    digest: str | None = None,
    facts: DocumentPathFacts | None = None,
) -> InputRecord:
    return InputRecord(
        source_id=source_id,
        locator_provenance="pinned_selected_body",
        selected_path=path,
        path_facts=facts or _path_facts(path),
        sha256=digest or sha256_bytes(body),
        byte_size=len(body),
        raw_bytes=body,
    )


def _request(
    operations: tuple[OperationRecord, ...],
    inputs: tuple[InputRecord, ...],
    *,
    path: str = "document.html",
    role: str = "primary",
    facts: DocumentPathFacts | None = None,
    include_analysis_artifacts: bool = False,
    family: str = "10-K",
) -> AcquisitionProcessRequest:
    return AcquisitionProcessRequest(
        target_id="target",
        family=family,
        role=role,
        target_type="exhibit" if role == "exhibit" else "primary",
        path_facts=facts or _path_facts(path),
        operations=operations,
        inputs=inputs,
        include_analysis_artifacts=include_analysis_artifacts,
    )


def test_raw_is_exact_identity_with_materialized_output_metadata() -> None:
    body = b"\x00\xff<raw>\n"
    request = _request(
        (OperationRecord("v1", "raw_bytes", ("source",), operation="raw"),),
        (_input(body=body),),
    )

    outcome = AcquisitionProcessor().process(request).outcomes[0]

    assert outcome.status == "ok"
    assert outcome.output_bytes == body
    assert outcome.output_text is None
    assert outcome.output_sha256 == sha256_bytes(body)
    assert outcome.output_byte_size == len(body)
    assert (outcome.handler_id, outcome.handler_version) == ("raw_identity", "1")


def test_render_to_txt_uses_generic_normalizer_fallback() -> None:
    body = b"<html><body><p>Filed text.</p></body></html>"
    operation = OperationRecord("v1", "text", ("source",), operation="render_to_txt")

    outcome = (
        AcquisitionProcessor()
        .process(_request((operation,), (_input(body=body),)))
        .outcomes[0]
    )

    assert outcome.status == "ok"
    assert outcome.output_text is not None
    assert "Filed text." in outcome.output_text
    assert b"<p>" not in outcome.output_bytes
    assert outcome.output_sha256 == sha256_bytes(outcome.output_bytes)
    assert outcome.output_byte_size == len(outcome.output_bytes)
    assert (outcome.handler_id, outcome.handler_version) == (
        "normalize_document",
        "1",
    )


def test_form_4_exhibit_can_use_generic_text_processing() -> None:
    operation = OperationRecord("v1", "text", ("source",), operation="render_to_txt")
    request = _request(
        (operation,),
        (_input(path="form4-ex99.htm"),),
        path="form4-ex99.htm",
        role="exhibit",
        family="4",
    )

    outcome = AcquisitionProcessor().process(request).outcomes[0]

    assert outcome.status == "ok"
    assert outcome.output_text is not None
    assert "Filed text." in outcome.output_text


def test_form_4_primary_with_exhibit_input_does_not_emit_xml() -> None:
    operation = OperationRecord("v1", "xml", ("source",), operation="render_to_xml")
    body = b"<html><body><h1>Exhibit 99.1</h1><p>Acme press release.</p></body></html>"
    request = _request(
        (operation,),
        (_input(path="ex99.htm", body=body),),
        path="ex99.htm",
        family="4",
    )

    outcome = AcquisitionProcessor().process(request).outcomes[0]

    assert outcome.status == "unsupported"
    assert outcome.error == "primary_document_identity_mismatch"
    assert outcome.output_bytes is None


def test_render_to_txt_normalizes_plain_text_route() -> None:
    body = b"A short filing statement.\n"
    operation = OperationRecord("v1", "text", ("source",), operation="render_to_txt")

    outcome = (
        AcquisitionProcessor()
        .process(
            _request(
                (operation,), (_input(path="filing.txt", body=body),), path="filing.txt"
            )
        )
        .outcomes[0]
    )

    assert outcome.status == "ok"
    assert outcome.output_text == "A short filing statement."
    assert outcome.output_bytes == b"A short filing statement."


def test_family_route_handler_precedes_generic_fallback() -> None:
    custom = ProcessingCapability(
        handler_id="10k_html_text",
        handler_version="7",
        operation="render_to_txt",
        input_facts="10-K HTML body",
        output_kind=HandlerOutputKind.TEXT,
    )
    capabilities = ProcessingCapabilityRegistry((*DEFAULT_CAPABILITIES.list(), custom))
    registry = HandlerRegistry(capabilities)
    registry.register(
        "normalize_document",
        "1",
        "render_to_txt",
        HandlerOutputKind.TEXT,
        lambda _body, _context: "generic",
    )
    registry.register(
        "10k_html_text",
        "7",
        "render_to_txt",
        HandlerOutputKind.TEXT,
        lambda _body, _context: "family-route",
        family="10-K",
        route=DocumentRoute.MARKUP,
    )
    operation = OperationRecord("v1", "text", ("source",), operation="render_to_txt")

    outcome = (
        AcquisitionProcessor(registry)
        .process(_request((operation,), (_input(),)))
        .outcomes[0]
    )

    assert outcome.output_text == "family-route"
    assert (outcome.handler_id, outcome.handler_version) == ("10k_html_text", "7")


def test_analysis_sidecars_are_returned_only_when_requested() -> None:
    capability = ProcessingCapability(
        handler_id="10k_html_text",
        handler_version="7",
        operation="render_to_txt",
        input_facts="10-K HTML body",
        output_kind=HandlerOutputKind.TEXT,
    )
    registry = HandlerRegistry(
        ProcessingCapabilityRegistry((*DEFAULT_CAPABILITIES.list(), capability))
    )
    registry.register(
        "10k_html_text",
        "7",
        "render_to_txt",
        HandlerOutputKind.TEXT,
        lambda _body, _context: HandlerOutput(
            "normalized",
            (HandlerSidecar("unparsed_sections.json", b'{"unparsed_sections":[]}'),),
        ),
        family="10-K",
        route=DocumentRoute.MARKUP,
    )
    operation = OperationRecord("v1", "text", ("source",), operation="render_to_txt")

    ordinary = (
        AcquisitionProcessor(registry)
        .process(_request((operation,), (_input(),)))
        .outcomes[0]
    )
    review = (
        AcquisitionProcessor(registry)
        .process(_request((operation,), (_input(),), include_analysis_artifacts=True))
        .outcomes[0]
    )

    assert ordinary.output_text == "normalized"
    assert ordinary.sidecar_outputs == ()
    assert review.sidecar_outputs[0].name == "unparsed_sections.json"
    assert review.sidecar_outputs[0].sha256 == sha256_bytes(
        review.sidecar_outputs[0].content
    )


def test_processor_distinguishes_archive_and_sgml_paths_with_slashes() -> None:
    markup = ProcessingCapability(
        handler_id="markup_text",
        handler_version="1",
        operation="render_to_txt",
        input_facts="markup body",
        output_kind=HandlerOutputKind.TEXT,
    )
    rendered = ProcessingCapability(
        handler_id="rendered_text",
        handler_version="1",
        operation="render_to_txt",
        input_facts="rendered markup body",
        output_kind=HandlerOutputKind.TEXT,
    )
    registry = HandlerRegistry(
        ProcessingCapabilityRegistry((*DEFAULT_CAPABILITIES.list(), markup, rendered))
    )
    registry.register(
        "markup_text",
        "1",
        "render_to_txt",
        HandlerOutputKind.TEXT,
        lambda _body, _context: "content route",
        family="10-K",
        route=DocumentRoute.MARKUP,
    )
    registry.register(
        "rendered_text",
        "1",
        "render_to_txt",
        HandlerOutputKind.TEXT,
        lambda _body, _context: "published route",
        family="10-K",
        route=DocumentRoute.RENDERED,
    )
    path = "xsl10K_X01/filing.htm"
    operation = OperationRecord("v1", "text", ("source",), operation="render_to_txt")

    for facts, expected in (
        (DocumentPathFacts.from_archive_path(path), "published route"),
        (DocumentPathFacts.from_sgml_filename(path), "content route"),
    ):
        request = _request(
            (operation,), (_input(path=path, facts=facts),), path=path, facts=facts
        )
        outcome = AcquisitionProcessor(registry).process(request).outcomes[0]
        assert outcome.output_text == expected


def test_flat_xml_and_unknown_operations_remain_unsupported() -> None:
    operation = OperationRecord("v1", "text", ("source",), operation="render_to_txt")
    unsupported_render = (
        AcquisitionProcessor()
        .process(
            _request((operation,), (_input(path="filing.xml"),), path="filing.xml")
        )
        .outcomes[0]
    )
    unknown_operation = (
        AcquisitionProcessor()
        .process(
            _request(
                (OperationRecord("v1", "xml", ("source",), operation="render_to_xml"),),
                (_input(),),
            )
        )
        .outcomes[0]
    )

    assert (unsupported_render.status, unsupported_render.error) == (
        "unsupported",
        "handler_not_registered",
    )
    assert (unknown_operation.status, unknown_operation.error) == (
        "unsupported",
        "handler_not_registered",
    )


@pytest.mark.parametrize(
    "path", ["filing.pdf", "filing.paper", "filing.zip", "filing.bin"]
)
def test_non_text_routes_do_not_use_normalizer_fallback(path: str) -> None:
    operation = OperationRecord("v1", "text", ("source",), operation="render_to_txt")

    outcome = (
        AcquisitionProcessor()
        .process(_request((operation,), (_input(path=path),), path=path))
        .outcomes[0]
    )

    assert (outcome.status, outcome.error) == ("unsupported", "handler_not_registered")


def test_invalid_source_and_handler_failure_do_not_suppress_sibling_results() -> None:
    custom = ProcessingCapability(
        handler_id="failing_text",
        handler_version="1",
        operation="render_to_txt",
        input_facts="test HTML body",
        output_kind=HandlerOutputKind.TEXT,
    )
    capabilities = ProcessingCapabilityRegistry((*DEFAULT_CAPABILITIES.list(), custom))
    registry = HandlerRegistry(capabilities)
    registry.register(
        "raw_identity",
        "1",
        "raw",
        HandlerOutputKind.RAW_BYTES,
        lambda body, _context: body,
    )

    def fail(_body: bytes, _context: object) -> str:
        raise RuntimeError("unstable detail is not returned")

    registry.register(
        "failing_text",
        "1",
        "render_to_txt",
        HandlerOutputKind.TEXT,
        fail,
        family="10-K",
        route=DocumentRoute.MARKUP,
    )
    operations = (
        OperationRecord("v1", "text", ("source",), operation="render_to_txt"),
        OperationRecord("v1", "raw_bytes", ("source",), operation="raw"),
        OperationRecord("v1", "raw_bytes", ("missing",), operation="raw"),
    )

    outcomes = (
        AcquisitionProcessor(registry)
        .process(_request(operations, (_input(),)))
        .outcomes
    )

    assert [(item.status, item.error) for item in outcomes] == [
        ("failed", "handler_failed:RuntimeError"),
        ("ok", None),
        ("failed", "missing_or_ambiguous_source"),
    ]
    assert outcomes[1].output_bytes == _input().raw_bytes


def test_invalid_input_digest_fails_operation() -> None:
    operation = OperationRecord("v1", "raw_bytes", ("source",), operation="raw")
    outcome = (
        AcquisitionProcessor()
        .process(_request((operation,), (_input(digest="0" * 64),)))
        .outcomes[0]
    )

    assert (outcome.status, outcome.error) == ("failed", "source_digest_mismatch")


def test_path_facts_type_is_validated() -> None:
    source = _input()
    invalid = InputRecord(
        source.source_id,
        source.locator_provenance,
        source.selected_path,
        DocumentPathFacts(
            path_context="document.html",
            path_shape=DocumentPathShape.FLAT,
            suffix=".html",
            suffix_class=DocumentSuffixClass.MARKUP,
        ),
        source.sha256,
        source.byte_size,
        source.raw_bytes,
    )
    request = _request(
        (OperationRecord("v1", "raw_bytes", ("source",), operation="raw"),),
        (invalid,),
    )
    request = AcquisitionProcessRequest(
        request.target_id,
        request.family,
        request.role,
        request.target_type,
        None,
        request.operations,
        request.inputs,
    )

    outcome = AcquisitionProcessor().process(request).outcomes[0]

    assert (outcome.status, outcome.error) == ("failed", "invalid_path_facts")
