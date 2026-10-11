"""Engine capability metadata and registry.

This module declares handler IDs, accepted input facts, output kind, and implementation
version. It is separate from the S6 acquisition catalog and binds IDs to code at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, Any


class HandlerOutputKind(StrEnum):
    """Type of output produced by a handler."""

    RAW_BYTES = "raw_bytes"
    TEXT = "text"
    XML = "xml"


@dataclass(frozen=True, slots=True)
class ProcessingCapability:
    """Metadata for a processing capability/handler.

    handler_id, handler_version, input_facts, output_kind.
    """

    handler_id: str
    handler_version: str
    input_facts: str
    output_kind: HandlerOutputKind


# Capability registry - maps handler_id to metadata
# Handlers are bound at runtime in registry.py
_CAPABILITIES: dict[str, ProcessingCapability] = {
    "html_to_text": ProcessingCapability(
        handler_id="html_to_text",
        handler_version="v1",
        input_facts="markup bytes (HTML/XML/XHTML)",
        output_kind=HandlerOutputKind.TEXT,
    ),
    "text_passthrough": ProcessingCapability(
        handler_id="text_passthrough",
        handler_version="v1",
        input_facts="text bytes",
        output_kind=HandlerOutputKind.TEXT,
    ),
    "xml_passthrough": ProcessingCapability(
        handler_id="xml_passthrough",
        handler_version="v1",
        input_facts="XML bytes",
        output_kind=HandlerOutputKind.XML,
    ),
}

# Capability catalog version for plan identity
_CATALOG_VERSION = "v1"


def get_capability(handler_id: str) -> ProcessingCapability | None:
    """Get capability metadata by handler ID."""
    return _CAPABILITIES.get(handler_id)


def has_capability(handler_id: str) -> bool:
    """Check if a capability is registered."""
    return handler_id in _CAPABILITIES


def list_capabilities() -> list[ProcessingCapability]:
    """List all registered capabilities."""
    return list(_CAPABILITIES.values())


def get_catalog_version() -> str:
    """Get the current capability catalog version."""
    return _CATALOG_VERSION


__all__ = [
    "get_capability",
    "get_catalog_version",
    "HandlerOutputKind",
    "has_capability",
    "list_capabilities",
    "ProcessingCapability",
]
