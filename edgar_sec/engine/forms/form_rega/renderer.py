"""XML renderer for SEC Regulation A filings: native pass-through only."""

from __future__ import annotations

from typing import TYPE_CHECKING

from edgar_sec.domain.forms.common.native_xml import SecXmlSchemaSpec
from edgar_sec.domain.forms.families.form_rega.taxonomy import (
    REGA_ANNUAL_XML_SPEC,
    REGA_EXIT_XML_SPEC,
    REGA_OFFERING_XML_SPEC,
)
from edgar_sec.engine.document_processing.outputs import HandlerOutput
from edgar_sec.engine.forms.common.native_xml import passthrough_sec_xml

if TYPE_CHECKING:
    from edgar_sec.engine.document_processing.registry import HandlerContext


def _render(
    raw_bytes: bytes,
    spec: SecXmlSchemaSpec,
    label: str,
) -> HandlerOutput:
    passthrough = passthrough_sec_xml(raw_bytes, spec)
    if passthrough is not None:
        return passthrough
    raise ValueError(f"payload is not a native Reg A {label} edgarSubmission document")


def render_rega_offering_to_xml(
    raw_bytes: bytes,
    context: HandlerContext | None = None,
) -> HandlerOutput:
    """Return native 1-A XML unchanged; refuse non-matching payloads."""
    return _render(raw_bytes, REGA_OFFERING_XML_SPEC, "1-A")


def render_rega_annual_to_xml(
    raw_bytes: bytes,
    context: HandlerContext | None = None,
) -> HandlerOutput:
    """Return native 1-K XML unchanged; refuse non-matching payloads."""
    return _render(raw_bytes, REGA_ANNUAL_XML_SPEC, "1-K")


def render_rega_exit_to_xml(
    raw_bytes: bytes,
    context: HandlerContext | None = None,
) -> HandlerOutput:
    """Return native 1-Z XML unchanged; refuse non-matching payloads."""
    return _render(raw_bytes, REGA_EXIT_XML_SPEC, "1-Z")


__all__ = [
    "render_rega_annual_to_xml",
    "render_rega_exit_to_xml",
    "render_rega_offering_to_xml",
]
