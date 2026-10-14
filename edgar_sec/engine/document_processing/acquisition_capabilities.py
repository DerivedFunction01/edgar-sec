"""Resolve acquisition operations against domain policy and runtime handlers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from edgar_sec.domain.document.path_facts import (
    DocumentPathFacts,
    DocumentPathShape,
    DocumentSuffixClass,
)
from edgar_sec.domain.document.route import DocumentRoute, content_route, document_route
from edgar_sec.domain.forms.common.aliases import resolve_alias
from edgar_sec.domain.forms.common.processing import AcquisitionOperation
from edgar_sec.domain.forms.families.processing_profiles import get_family_profile
from edgar_sec.engine.document_processing.capabilities import (
    HandlerOutputKind,
    operation_output_kind,
)
from edgar_sec.engine.document_processing.registry import (
    DEFAULT_HANDLER_REGISTRY,
    HandlerRegistration,
    HandlerRegistry,
)


class CapabilityStatus(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class CapabilityEntry:
    family: str
    role: str
    operation: str
    status: CapabilityStatus
    capability_id: str | None = None
    capability_version: str | None = None
    handler_id: str | None = None
    handler_version: str | None = None
    output_kind: str | None = None
    registration: HandlerRegistration | None = None

    @property
    def pins(self) -> tuple[str, str, str, str, str] | None:
        if self.status is not CapabilityStatus.SUPPORTED:
            return None
        if any(
            value is None
            for value in (
                self.capability_id,
                self.capability_version,
                self.handler_id,
                self.handler_version,
                self.output_kind,
            )
        ):
            return None
        return (
            self.capability_id,
            self.capability_version,
            self.handler_id,
            self.handler_version,
            self.output_kind,
        )


def resolve_acquisition_capability(
    family: str,
    role: str,
    operation: str,
    facts: DocumentPathFacts,
    route: DocumentRoute | None = None,
    *,
    handlers: HandlerRegistry = DEFAULT_HANDLER_REGISTRY,
) -> CapabilityEntry:
    normalized_family = resolve_alias(family) or family
    effective_route = route or _route_from_facts(facts)
    capability_id: str | None = None
    capability_version: str | None = None
    handler_id: str | None = None
    if operation == "raw":
        capability_id = "raw.selected_source"
        capability_version = "v1"
        handler_id = "raw_identity"
    else:
        profile = get_family_profile(family)
        try:
            permitted = profile is not None and (
                AcquisitionOperation(operation) in profile.allowed_operations
            )
        except ValueError:
            permitted = False
        if permitted:
            capability_version = profile.version
            if operation == "render_to_txt":
                if facts.suffix_class is DocumentSuffixClass.TEXT:
                    capability_id = "text.plain"
                elif facts.suffix_class is DocumentSuffixClass.MARKUP:
                    capability_id = "text.markup"
                elif (
                    facts.suffix_class is DocumentSuffixClass.XML
                    and facts.path_shape is DocumentPathShape.NESTED
                    and facts.path_context.split("/", 1)[0].casefold().startswith("xsl")
                ):
                    capability_id = "text.rendered_markup"
                if capability_id is not None:
                    handler_id = "normalize_document"
            elif operation == "render_to_xml":
                if (
                    normalized_family == "4"
                    and role == "primary"
                    and facts.suffix == ".htm"
                    and facts.suffix_class is DocumentSuffixClass.MARKUP
                ):
                    capability_id = "form4.htm.render_to_xml"
                    handler_id = "form4_html_to_xml"

    registration = handlers.resolve(operation, normalized_family, effective_route)
    expected_output_kind = operation_output_kind(operation)
    registered_capability = (
        handlers.capability_for(registration.handler_id)
        if registration is not None
        else None
    )
    if (
        capability_id is None
        or capability_version is None
        or expected_output_kind is None
        or registration is None
        or registered_capability is None
        or registration.operation != operation
        or registration.output_kind is not expected_output_kind
        or registered_capability.operation != operation
        or registered_capability.handler_version != registration.handler_version
        or registered_capability.output_kind is not expected_output_kind
        or not _route_supports(operation, effective_route)
    ):
        return CapabilityEntry(
            normalized_family,
            role,
            operation,
            CapabilityStatus.UNSUPPORTED,
        )
    return CapabilityEntry(
        family=normalized_family,
        role=role,
        operation=operation,
        status=CapabilityStatus.SUPPORTED,
        capability_id=capability_id,
        capability_version=capability_version,
        handler_id=registration.handler_id,
        handler_version=registration.handler_version,
        output_kind=registration.output_kind.value,
        registration=registration,
    )


def _route_from_facts(facts: DocumentPathFacts) -> DocumentRoute:
    if facts.path_shape is DocumentPathShape.NESTED:
        return document_route(facts.path_context)
    return content_route(facts.path_context)


def _route_supports(operation: str, route: DocumentRoute) -> bool:
    if operation == "render_to_txt":
        return route in {
            DocumentRoute.MARKUP,
            DocumentRoute.RENDERED,
            DocumentRoute.TEXT,
        }
    return True


__all__ = [
    "CapabilityEntry",
    "CapabilityStatus",
    "resolve_acquisition_capability",
]
