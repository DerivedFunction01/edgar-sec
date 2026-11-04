"""XML renderer for ABS asset-data exhibits: native pass-through only."""

from __future__ import annotations

from typing import TYPE_CHECKING

from edgar_sec.engine.document_processing.outputs import HandlerOutput
from edgar_sec.engine.forms.common.native_xml import inspect_sec_xml_root
from edgar_sec.engine.forms.common.unparsed import (
    UNPARSED_SECTIONS_FILE,
    serialize_unparsed_sections,
)
from edgar_sec.engine.document_processing.outputs import HandlerSidecar
from edgar_sec.engine.forms.form_abs_ee.stream import classify_asset_root

if TYPE_CHECKING:
    from edgar_sec.engine.document_processing.registry import HandlerContext


def render_abs_ee_to_xml(
    raw_bytes: bytes,
    context: HandlerContext | None = None,
) -> HandlerOutput:
    """Return a native asset-data document unchanged; refuse anything else."""
    root_info = inspect_sec_xml_root(raw_bytes)
    if root_info is not None and classify_asset_root(*root_info) is not None:
        return HandlerOutput(
            content=raw_bytes,
            sidecars=(
                HandlerSidecar(UNPARSED_SECTIONS_FILE, serialize_unparsed_sections(())),
            ),
        )
    raise ValueError("payload is not an ABS asset-data document")


__all__ = ["render_abs_ee_to_xml"]
