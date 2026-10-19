"""Public rendering entry point for Schedule 13D/13G to SEC XML."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

from edgar_sec.domain.document.path_facts import DocumentSuffixClass
from edgar_sec.domain.document.route import DocumentRoute
from edgar_sec.engine.forms.normalize import normalize_document
from .parser import parse_beneficial_ownership_document
from .render_to_xml import (
    SCHEDULE_13D_NS,
    SCHEDULE_13G_NS,
    build_beneficial_ownership_xml,
)

if TYPE_CHECKING:
    from edgar_sec.engine.document_processing.registry import HandlerContext

_NATIVE_ROOTS = {
    f"{{{SCHEDULE_13D_NS}}}edgarSubmission",
    f"{{{SCHEDULE_13G_NS}}}edgarSubmission",
}


def _is_native_xml(raw_bytes: bytes) -> bool:
    try:
        root = ET.fromstring(raw_bytes)
    except ET.ParseError:
        return False
    return root.tag in _NATIVE_ROOTS


def render_beneficial_ownership_to_xml(
    raw_bytes: bytes, context: HandlerContext | None = None
) -> bytes:
    """Renders raw Schedule 13D/13G filing payload into conforming SEC XML."""
    if _is_native_xml(raw_bytes):
        return raw_bytes
    form = context.family if context is not None else "13D"
    path = context.selected_path if context is not None else None
    route = context.route if context is not None else None
    normalized = normalize_document(
        raw_bytes,
        form=form,
        document_path=path,
        content_route=route,
    )
    if context is not None:
        if (
            route is DocumentRoute.TEXT
            and context.path_facts.suffix_class is not DocumentSuffixClass.TEXT
        ):
            raise ValueError(
                "Beneficial ownership text rendering requires a .txt source"
            )
        if (
            route in {DocumentRoute.MARKUP, DocumentRoute.RENDERED}
            and context.path_facts.suffix_class is not DocumentSuffixClass.MARKUP
        ):
            raise ValueError(
                "Beneficial ownership markup rendering requires an HTML source"
            )
        if route not in {
            DocumentRoute.MARKUP,
            DocumentRoute.RENDERED,
            DocumentRoute.TEXT,
        }:
            raise ValueError("unsupported beneficial ownership source route")
    doc = parse_beneficial_ownership_document(normalized, form=form)
    return build_beneficial_ownership_xml(doc)


def render_schedule13d_to_xml(
    raw_bytes: bytes, context: HandlerContext | None = None
) -> bytes:
    return render_beneficial_ownership_to_xml(raw_bytes, context)


def render_schedule13g_to_xml(
    raw_bytes: bytes, context: HandlerContext | None = None
) -> bytes:
    return render_beneficial_ownership_to_xml(raw_bytes, context)


__all__ = [
    "render_beneficial_ownership_to_xml",
    "render_schedule13d_to_xml",
    "render_schedule13g_to_xml",
]
