"""Shared canonical XML construction for SEC form renderers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import xml.etree.ElementTree as ET

from edgar_sec.engine.document_processing.outputs import HandlerOutput, HandlerSidecar
from edgar_sec.engine.forms.common.unparsed import (
    UNPARSED_SECTIONS_FILE,
    serialize_unparsed_sections,
)


def root_element(tag: str, attrib: dict[str, str] | None = None) -> ET.Element:
    """Create a detached root element."""
    return ET.Element(tag, attrib or {})


def child_element(parent: ET.Element, tag: str) -> ET.Element:
    """Append an empty child element and return it."""
    return ET.SubElement(parent, tag)


def add_text_element(parent: ET.Element, tag: str, text: str | None) -> ET.Element:
    """Append a child element, setting its text when text is not None."""
    elem = ET.SubElement(parent, tag)
    if text is not None:
        elem.text = text
    return elem


def serialize_canonical_xml(root: ET.Element) -> bytes:
    """Serialize a canonical XML tree as UTF-8 bytes with declaration."""
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def canonical_xml_output(
    root: ET.Element,
    unparsed_sections: Sequence[Mapping[str, object]] = (),
) -> HandlerOutput:
    """Wrap a canonical XML tree in the shared handler-output envelope."""
    return HandlerOutput(
        content=serialize_canonical_xml(root),
        sidecars=(
            HandlerSidecar(
                UNPARSED_SECTIONS_FILE,
                serialize_unparsed_sections(unparsed_sections),
            ),
        ),
    )


__all__ = [
    "add_text_element",
    "canonical_xml_output",
    "child_element",
    "root_element",
    "serialize_canonical_xml",
]
