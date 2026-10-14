"""Versioned metadata for document-processing handlers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

_OPERATIONS = frozenset({"raw", "render_to_txt", "render_to_xml"})
_OUTPUT_BY_OPERATION = {
    "raw": "raw_bytes",
    "render_to_txt": "text",
    "render_to_xml": "xml",
}


class HandlerOutputKind(StrEnum):
    RAW_BYTES = "raw_bytes"
    TEXT = "text"
    XML = "xml"


def operation_output_kind(operation: str) -> HandlerOutputKind | None:
    value = _OUTPUT_BY_OPERATION.get(operation)
    return HandlerOutputKind(value) if value is not None else None


@dataclass(frozen=True, slots=True)
class ProcessingCapability:
    handler_id: str
    handler_version: str
    operation: str
    input_facts: str
    output_kind: HandlerOutputKind


class ProcessingCapabilityRegistry:
    def __init__(self, capabilities: Iterable[ProcessingCapability] = ()) -> None:
        self._capabilities: dict[str, ProcessingCapability] = {}
        for capability in capabilities:
            self.register(capability)

    def register(self, capability: ProcessingCapability) -> None:
        if not isinstance(capability, ProcessingCapability):
            raise TypeError("capability must be ProcessingCapability")
        if not isinstance(capability.handler_id, str) or not isinstance(
            capability.handler_version, str
        ):
            raise ValueError("handler identity and version must be strings")
        if not capability.handler_id.strip() or not capability.handler_version.strip():
            raise ValueError("handler identity and version must be non-empty")
        if capability.operation not in _OPERATIONS:
            raise ValueError("operation is outside the supported vocabulary")
        if (
            not isinstance(capability.input_facts, str)
            or not capability.input_facts.strip()
        ):
            raise ValueError("operation and input facts must be non-empty")
        if not isinstance(capability.output_kind, HandlerOutputKind):
            raise ValueError("handler output kind is invalid")
        if capability.output_kind.value != _OUTPUT_BY_OPERATION[capability.operation]:
            raise ValueError("handler output kind does not match operation")
        if capability.handler_id in self._capabilities:
            raise ValueError(f"duplicate capability: {capability.handler_id}")
        self._capabilities[capability.handler_id] = capability

    def get(self, handler_id: str) -> ProcessingCapability | None:
        return self._capabilities.get(handler_id)

    def list(self) -> tuple[ProcessingCapability, ...]:
        return tuple(self._capabilities.values())


CATALOG_VERSION = "v2"
DEFAULT_CAPABILITIES = ProcessingCapabilityRegistry(
    (
        ProcessingCapability(
            handler_id="raw_identity",
            handler_version="1",
            operation="raw",
            input_facts="selected source bytes",
            output_kind=HandlerOutputKind.RAW_BYTES,
        ),
        ProcessingCapability(
            handler_id="normalize_document",
            handler_version="1",
            operation="render_to_txt",
            input_facts="text, markup, or rendered markup route",
            output_kind=HandlerOutputKind.TEXT,
        ),
    )
)


def get_capability(handler_id: str) -> ProcessingCapability | None:
    return DEFAULT_CAPABILITIES.get(handler_id)


def has_capability(handler_id: str) -> bool:
    return get_capability(handler_id) is not None


def list_capabilities() -> list[ProcessingCapability]:
    return list(DEFAULT_CAPABILITIES.list())


def get_catalog_version() -> str:
    return CATALOG_VERSION


__all__ = [
    "CATALOG_VERSION",
    "DEFAULT_CAPABILITIES",
    "HandlerOutputKind",
    "ProcessingCapability",
    "ProcessingCapabilityRegistry",
    "get_capability",
    "get_catalog_version",
    "has_capability",
    "list_capabilities",
    "operation_output_kind",
]
