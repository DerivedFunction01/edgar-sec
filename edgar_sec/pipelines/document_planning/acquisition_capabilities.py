"""S6 acquisition capability catalog.

Provides generic resolution of acquisition operations based on path facts
and engine handler metadata. Family-specific allowed operations are declared in domain/forms/families/.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CapabilityStatus(StrEnum):
    """Status of an operation for a given context."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    NOT_APPLICABLE = "not_applicable"


class SourceStrategy(StrEnum):
    """Strategy for obtaining source data."""

    PRIMARY_BODY = "primary_body"
    ARCHIVE_ROOT_XML = "archive_root_xml"
    SEPARATE_FETCH = "separate_fetch"


class OutputKind(StrEnum):
    """Type of output produced by an operation."""

    RAW_BYTES = "raw_bytes"
    TEXT = "text"
    XML = "xml"


@dataclass(frozen=True, slots=True)
class CapabilityEntry:
    """Entry in the acquisition capability catalog."""

    family: str
    role: str
    operation: str
    status: CapabilityStatus
    source_strategy: SourceStrategy | None
    output_kind: OutputKind | None
    handler_id: str | None = None
    handler_version: str | None = None


CATALOG_VERSION = "v1"


def get_capability(
    family: str,
    role: str,
    path_shape: str,
    suffix_class: str,
    operation: str,
) -> CapabilityEntry:
    """Resolve capability for a given context using generic path-facts rules."""
    # Path-facts rules that apply generically
    if operation == "raw":
        return CapabilityEntry(
            family=family,
            role=role,
            operation=operation,
            status=CapabilityStatus.SUPPORTED,
            source_strategy=SourceStrategy.PRIMARY_BODY,
            output_kind=OutputKind.RAW_BYTES,
        )

    if operation == "render_to_txt":
        # Nested .xml paths (XSL rendering) serve HTML
        if (suffix_class == "xml" and path_shape == "nested") or (
            suffix_class in ("markup", "text")
        ):
            return CapabilityEntry(
                family=family,
                role=role,
                operation=operation,
                status=CapabilityStatus.SUPPORTED,
                source_strategy=SourceStrategy.PRIMARY_BODY,
                output_kind=OutputKind.TEXT,
                handler_id="html_to_text"
                if suffix_class == "markup"
                or (suffix_class == "xml" and path_shape == "nested")
                else "text_passthrough",
                handler_version="v1",
            )

    if operation == "render_to_xml":
        if path_shape == "nested" and suffix_class == "xml":
            return CapabilityEntry(
                family=family,
                role=role,
                operation=operation,
                status=CapabilityStatus.SUPPORTED,
                source_strategy=SourceStrategy.ARCHIVE_ROOT_XML,
                output_kind=OutputKind.XML,
                handler_id="xml_passthrough",
                handler_version="v1",
            )

    return CapabilityEntry(
        family=family,
        role=role,
        operation=operation,
        status=CapabilityStatus.UNSUPPORTED,
        source_strategy=None,
        output_kind=None,
    )


def get_source_strategy(
    family: str,
    role: str,
    path_shape: str,
    suffix_class: str,
    operation: str,
) -> SourceStrategy | None:
    """Get the source strategy for a given operation context."""
    entry = get_capability(family, role, path_shape, suffix_class, operation)
    return entry.source_strategy


def get_output_kind(
    family: str,
    role: str,
    path_shape: str,
    suffix_class: str,
    operation: str,
) -> OutputKind | None:
    """Get the output kind for a given operation context."""
    entry = get_capability(family, role, path_shape, suffix_class, operation)
    return entry.output_kind


def is_operation_supported(
    family: str,
    role: str,
    path_shape: str,
    suffix_class: str,
    operation: str,
) -> bool:
    """Check if an operation is supported for a given context."""
    entry = get_capability(family, role, path_shape, suffix_class, operation)
    return entry.status == CapabilityStatus.SUPPORTED


__all__ = [
    "CATALOG_VERSION",
    "CapabilityEntry",
    "CapabilityStatus",
    "get_capability",
    "get_output_kind",
    "get_source_strategy",
    "is_operation_supported",
    "OutputKind",
    "SourceStrategy",
]
