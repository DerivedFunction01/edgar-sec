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
from edgar_sec.engine.document_processing.outputs import HandlerOutput


@dataclass(frozen=True, slots=True)
class HandlerContext:
    family: str
    role: str
    target_type: str
    selected_path: str
    path_facts: DocumentPathFacts
    route: DocumentRoute
    include_analysis_artifacts: bool = False
    filing_date: str | None = None
    report_date: str | None = None
    form_type: str | None = None


Handler = Callable[[bytes, HandlerContext], bytes | str | HandlerOutput]


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


def _normalize_pdf_document(raw_bytes: bytes, _context: HandlerContext) -> str:
    from edgar_sec.engine.document_processing.pdf import convert_pdf_to_text

    return convert_pdf_to_text(raw_bytes).text


def _ownership_html_to_xml(
    raw_bytes: bytes, context: HandlerContext
) -> bytes | HandlerOutput:
    from edgar_sec.engine.forms.ownership.render_to_xml import render_ownership_to_xml

    return render_ownership_to_xml(raw_bytes, context)


def _form144_html_to_xml(
    raw_bytes: bytes, context: HandlerContext
) -> bytes | HandlerOutput:
    from edgar_sec.engine.forms.form144.render_to_xml import render_form144_to_xml

    return render_form144_to_xml(raw_bytes, context)


def _schedule13d_to_xml(
    raw_bytes: bytes, context: HandlerContext
) -> bytes | HandlerOutput:
    from edgar_sec.engine.forms.beneficial_ownership.renderer import (
        render_schedule13d_to_xml,
    )

    return render_schedule13d_to_xml(raw_bytes, context)


def _schedule13g_to_xml(
    raw_bytes: bytes, context: HandlerContext
) -> bytes | HandlerOutput:
    from edgar_sec.engine.forms.beneficial_ownership.renderer import (
        render_schedule13g_to_xml,
    )

    return render_schedule13g_to_xml(raw_bytes, context)


def _form_d_to_xml(raw_bytes: bytes, context: HandlerContext) -> bytes | HandlerOutput:
    from edgar_sec.engine.forms.form_d.renderer import render_form_d_to_xml

    return render_form_d_to_xml(raw_bytes, context)


def _form_13f_to_xml(
    raw_bytes: bytes, context: HandlerContext
) -> bytes | HandlerOutput:
    from edgar_sec.engine.forms.form_13f.renderer import render_form_13f_to_xml

    return render_form_13f_to_xml(raw_bytes, context)


def _form_25nse_to_xml(
    raw_bytes: bytes, context: HandlerContext
) -> bytes | HandlerOutput:
    from edgar_sec.engine.forms.form_25nse.renderer import render_form_25nse_to_xml

    return render_form_25nse_to_xml(raw_bytes, context)


def _form_c_to_xml(raw_bytes: bytes, context: HandlerContext) -> bytes | HandlerOutput:
    from edgar_sec.engine.forms.form_c.renderer import render_form_c_to_xml

    return render_form_c_to_xml(raw_bytes, context)


def _abs_ee_to_xml(raw_bytes: bytes, context: HandlerContext) -> bytes | HandlerOutput:
    from edgar_sec.engine.forms.form_abs_ee.renderer import render_abs_ee_to_xml

    return render_abs_ee_to_xml(raw_bytes, context)


def _form_nport_to_xml(
    raw_bytes: bytes, context: HandlerContext
) -> bytes | HandlerOutput:
    from edgar_sec.engine.forms.form_nport.renderer import render_nport_to_xml

    return render_nport_to_xml(raw_bytes, context)


def _form_ncen_to_xml(
    raw_bytes: bytes, context: HandlerContext
) -> bytes | HandlerOutput:
    from edgar_sec.engine.forms.form_ncen.renderer import render_ncen_to_xml

    return render_ncen_to_xml(raw_bytes, context)


def _form_npx_to_xml(
    raw_bytes: bytes, context: HandlerContext
) -> bytes | HandlerOutput:
    from edgar_sec.engine.forms.form_npx.renderer import render_npx_to_xml

    return render_npx_to_xml(raw_bytes, context)


def _form_nmfp_to_xml(
    raw_bytes: bytes, context: HandlerContext
) -> bytes | HandlerOutput:
    from edgar_sec.engine.forms.form_nmfp.renderer import render_nmfp_to_xml

    return render_nmfp_to_xml(raw_bytes, context)


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
        "normalize_pdf_document",
        "1",
        "render_to_txt",
        HandlerOutputKind.TEXT,
        _normalize_pdf_document,
        route=DocumentRoute.BINARY,
    )
    registry.register(
        "form3_html_to_xml",
        "2",
        "render_to_xml",
        HandlerOutputKind.XML,
        _ownership_html_to_xml,
        family="3",
    )
    registry.register(
        "form4_html_to_xml",
        "2",
        "render_to_xml",
        HandlerOutputKind.XML,
        _ownership_html_to_xml,
        family="4",
    )
    registry.register(
        "form5_html_to_xml",
        "2",
        "render_to_xml",
        HandlerOutputKind.XML,
        _ownership_html_to_xml,
        family="5",
    )
    registry.register(
        "form144_html_to_xml",
        "2",
        "render_to_xml",
        HandlerOutputKind.XML,
        _form144_html_to_xml,
        family="144",
    )
    registry.register(
        "schedule13d_to_xml",
        "2",
        "render_to_xml",
        HandlerOutputKind.XML,
        _schedule13d_to_xml,
        family="13D",
    )
    registry.register(
        "schedule13g_to_xml",
        "2",
        "render_to_xml",
        HandlerOutputKind.XML,
        _schedule13g_to_xml,
        family="13G",
    )
    registry.register(
        "form_d_to_xml",
        "1",
        "render_to_xml",
        HandlerOutputKind.XML,
        _form_d_to_xml,
        family="D",
    )
    registry.register(
        "form_13f_to_xml",
        "1",
        "render_to_xml",
        HandlerOutputKind.XML,
        _form_13f_to_xml,
        family="13F",
    )
    registry.register(
        "form_25nse_to_xml",
        "1",
        "render_to_xml",
        HandlerOutputKind.XML,
        _form_25nse_to_xml,
        family="25-NSE",
    )
    registry.register(
        "form_c_to_xml",
        "1",
        "render_to_xml",
        HandlerOutputKind.XML,
        _form_c_to_xml,
        family="C",
    )
    registry.register(
        "abs_ee_to_xml",
        "1",
        "render_to_xml",
        HandlerOutputKind.XML,
        _abs_ee_to_xml,
        family="ABS-EE",
    )
    registry.register(
        "form_nport_to_xml",
        "1",
        "render_to_xml",
        HandlerOutputKind.XML,
        _form_nport_to_xml,
        family="N-PORT",
    )
    registry.register(
        "form_ncen_to_xml",
        "1",
        "render_to_xml",
        HandlerOutputKind.XML,
        _form_ncen_to_xml,
        family="N-CEN",
    )
    registry.register(
        "form_npx_to_xml",
        "1",
        "render_to_xml",
        HandlerOutputKind.XML,
        _form_npx_to_xml,
        family="N-PX",
    )
    registry.register(
        "form_nmfp_to_xml",
        "1",
        "render_to_xml",
        HandlerOutputKind.XML,
        _form_nmfp_to_xml,
        family="N-MFP",
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
