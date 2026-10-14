"""Tests for capability-validated handler registration."""

from __future__ import annotations

import pytest

from edgar_sec.engine.document_processing.capabilities import (
    DEFAULT_CAPABILITIES,
    HandlerOutputKind,
    ProcessingCapability,
    ProcessingCapabilityRegistry,
    operation_output_kind,
)
from edgar_sec.engine.document_processing.registry import HandlerRegistry


def test_registration_requires_matching_capability_metadata() -> None:
    registry = HandlerRegistry()

    with pytest.raises(ValueError, match="no capability metadata"):
        registry.register(
            "unlisted",
            "1",
            "render_to_txt",
            HandlerOutputKind.TEXT,
            lambda _body, _context: "text",
        )
    with pytest.raises(ValueError, match="does not match capability"):
        registry.register(
            "normalize_document",
            "2",
            "render_to_txt",
            HandlerOutputKind.TEXT,
            lambda _body, _context: "text",
        )


def test_duplicate_capability_ids_are_rejected() -> None:
    capability = DEFAULT_CAPABILITIES.get("normalize_document")
    assert capability is not None

    with pytest.raises(ValueError, match="duplicate capability"):
        ProcessingCapabilityRegistry((capability, capability))


def test_capability_rejects_empty_metadata() -> None:
    with pytest.raises(ValueError, match="identity and version"):
        ProcessingCapabilityRegistry(
            (
                ProcessingCapability(
                    handler_id="",
                    handler_version="1",
                    operation="raw",
                    input_facts="source bytes",
                    output_kind=HandlerOutputKind.RAW_BYTES,
                ),
            )
        )


def test_capability_rejects_unknown_operation() -> None:
    with pytest.raises(ValueError, match="supported vocabulary"):
        ProcessingCapabilityRegistry(
            (
                ProcessingCapability(
                    handler_id="unknown_operation",
                    handler_version="1",
                    operation="copy_with_changes",
                    input_facts="source bytes",
                    output_kind=HandlerOutputKind.RAW_BYTES,
                ),
            )
        )


def test_capability_rejects_operation_output_mismatch() -> None:
    with pytest.raises(ValueError, match="does not match operation"):
        ProcessingCapabilityRegistry(
            (
                ProcessingCapability(
                    handler_id="raw_as_text",
                    handler_version="1",
                    operation="raw",
                    input_facts="source bytes",
                    output_kind=HandlerOutputKind.TEXT,
                ),
            )
        )


def test_registry_exposes_handler_capability_and_operation_output_contract() -> None:
    registry = HandlerRegistry()
    assert registry.capability_for("normalize_document") == DEFAULT_CAPABILITIES.get(
        "normalize_document"
    )
    assert operation_output_kind("render_to_txt") is HandlerOutputKind.TEXT
    assert operation_output_kind("unknown") is None
