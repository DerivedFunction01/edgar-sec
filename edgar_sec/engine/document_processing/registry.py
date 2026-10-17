"""Validated runtime bindings for document-processing handlers."""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Callable

from edgar_sec.domain.document.path_facts import DocumentPathFacts
from edgar_sec.domain.document.route import DocumentRoute
from edgar_sec.engine.document_processing.capabilities import (
    DEFAULT_CAPABILITIES,
    HandlerOutputKind,
    ProcessingCapability,
    ProcessingCapabilityRegistry,
)


@dataclass(frozen=True, slots=True)
class HandlerContext:
    family: str
    role: str
    target_type: str
    selected_path: str
    path_facts: DocumentPathFacts
    route: DocumentRoute


Handler = Callable[[bytes, HandlerContext], bytes | str]


@dataclass(frozen=True, slots=True)
class HandlerRegistration:
    handler_id: str
    handler_version: str
    operation: str
    output_kind: HandlerOutputKind
    handler: Handler
    family: str | None = None
    route: DocumentRoute | None = None


class HandlerRegistry:
    def __init__(
        self,
        capabilities: ProcessingCapabilityRegistry = DEFAULT_CAPABILITIES,
    ) -> None:
        self._capabilities = capabilities
        self._handlers: dict[
            tuple[str, str | None, DocumentRoute | None], HandlerRegistration
        ] = {}

    def register(
        self,
        handler_id: str,
        handler_version: str,
        operation: str,
        output_kind: HandlerOutputKind,
        handler: Handler,
        *,
        family: str | None = None,
        route: DocumentRoute | None = None,
    ) -> None:
        capability = self._capabilities.get(handler_id)
        if capability is None:
            raise ValueError(f"handler has no capability metadata: {handler_id}")
        if (
            capability.handler_version != handler_version
            or capability.operation != operation
            or capability.output_kind is not output_kind
        ):
            raise ValueError(
                f"handler metadata does not match capability: {handler_id}"
            )
        if not callable(handler):
            raise TypeError("handler must be callable")
        normalized_family = family.strip().casefold() if family is not None else None
        if family is not None and not normalized_family:
            raise ValueError("family selector must be non-empty")
        if route is not None and not isinstance(route, DocumentRoute):
            raise ValueError("route selector must be a DocumentRoute")
        key = (operation, normalized_family, route)
        if key in self._handlers:
            raise ValueError(f"duplicate handler selector: {key!r}")
        self._handlers[key] = HandlerRegistration(
            handler_id=handler_id,
            handler_version=handler_version,
            operation=operation,
            output_kind=output_kind,
            handler=handler,
            family=normalized_family,
            route=route,
        )

    def resolve(
        self,
        operation: str,
        family: str,
        route: DocumentRoute,
    ) -> HandlerRegistration | None:
        normalized_family = family.strip().casefold()
        candidates = (
            (operation, normalized_family, route),
            (operation, normalized_family, None),
            (operation, None, route),
            (operation, None, None),
        )
        return next(
            (self._handlers[key] for key in candidates if key in self._handlers), None
        )

    def get(self, handler_id: str, operation: str) -> HandlerRegistration | None:
        matches = [
            registration
            for registration in self._handlers.values()
            if registration.handler_id == handler_id
            and registration.operation == operation
        ]
        if len(matches) == 1:
            return matches[0]
        return next(
            (
                registration
                for registration in matches
                if registration.family is None and registration.route is None
            ),
            None,
        )

    def capability_for(self, handler_id: str) -> ProcessingCapability | None:
        return self._capabilities.get(handler_id)

    def list(self) -> tuple[HandlerRegistration, ...]:
        return tuple(self._handlers.values())


def _raw_identity(raw_bytes: bytes, _context: HandlerContext) -> bytes:
    return raw_bytes


def _normalize_document(raw_bytes: bytes, context: HandlerContext) -> str:
    from edgar_sec.engine.forms.normalize import normalize_document

    result = normalize_document(
        raw_bytes,
        form=context.family if context.role == "primary" else None,
        document_path=context.selected_path,
        content_route=context.route,
    )
    return result.text


def _form4_html_to_xml(raw_bytes: bytes, context: HandlerContext) -> bytes:
    from edgar_sec.engine.forms.ownership.render_to_xml import render_form4_to_xml

    return render_form4_to_xml(raw_bytes, context)


def _form144_html_to_xml(raw_bytes: bytes, context: HandlerContext) -> bytes:
    from edgar_sec.engine.forms.form144.render_to_xml import render_form144_to_xml

    return render_form144_to_xml(raw_bytes, context)


def default_handler_registry() -> HandlerRegistry:
    registry = HandlerRegistry()
    registry.register(
        "raw_identity",
        "1",
        "raw",
        HandlerOutputKind.RAW_BYTES,
        _raw_identity,
    )
    registry.register(
        "normalize_document",
        "1",
        "render_to_txt",
        HandlerOutputKind.TEXT,
        _normalize_document,
    )
    registry.register(
        "form3_html_to_xml",
        "1",
        "render_to_xml",
        HandlerOutputKind.XML,
        _form4_html_to_xml,
        family="3",
    )
    registry.register(
        "form4_html_to_xml",
        "1",
        "render_to_xml",
        HandlerOutputKind.XML,
        _form4_html_to_xml,
        family="4",
    )
    registry.register(
        "form5_html_to_xml",
        "1",
        "render_to_xml",
        HandlerOutputKind.XML,
        _form4_html_to_xml,
        family="5",
    )
    registry.register(
        "form144_html_to_xml",
        "1",
        "render_to_xml",
        HandlerOutputKind.XML,
        _form144_html_to_xml,
        family="144",
    )
    return registry


DEFAULT_HANDLER_REGISTRY = default_handler_registry()


__all__ = [
    "DEFAULT_HANDLER_REGISTRY",
    "Handler",
    "HandlerContext",
    "HandlerRegistration",
    "HandlerRegistry",
    "default_handler_registry",
]
