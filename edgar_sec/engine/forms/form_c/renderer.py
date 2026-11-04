"""XML renderer for SEC Form C filings: native pass-through only."""

from __future__ import annotations

from typing import TYPE_CHECKING

from edgar_sec.domain.forms.families.form_c.taxonomy import FORMC_XML_SPEC
from edgar_sec.engine.document_processing.outputs import HandlerOutput
from edgar_sec.engine.forms.common.native_xml import passthrough_sec_xml

if TYPE_CHECKING:
    from edgar_sec.engine.document_processing.registry import HandlerContext


def render_form_c_to_xml(
    raw_bytes: bytes,
    context: HandlerContext | None = None,
) -> HandlerOutput:
    """Return native Form C XML unchanged; refuse non-matching payloads."""
    passthrough = passthrough_sec_xml(raw_bytes, FORMC_XML_SPEC)
    if passthrough is not None:
        return passthrough
    raise ValueError("payload is not a native Form C edgarSubmission document")


__all__ = ["render_form_c_to_xml"]
