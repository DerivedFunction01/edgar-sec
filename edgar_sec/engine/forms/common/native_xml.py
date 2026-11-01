"""Streaming detection and passthrough for native SEC XML filings."""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET

from edgar_sec.domain.forms.common.native_xml import SecXmlSchemaSpec
from edgar_sec.engine.document_processing.outputs import HandlerOutput, HandlerSidecar
from edgar_sec.engine.forms.common.extraction import local_name
from edgar_sec.engine.forms.common.unparsed import serialize_unparsed_sections


def inspect_sec_xml_root(raw_bytes: bytes) -> tuple[str, str] | None:
    """Return (namespace_uri, local_tag) for well-formed XML, or None if not XML."""
    stripped = raw_bytes.lstrip()
    if not (stripped.startswith(b"<") or stripped.startswith(b"<?xml")):
        return None
    try:
        for _, elem in ET.iterparse(io.BytesIO(raw_bytes), events=("start",)):
            tag = elem.tag
            if not isinstance(tag, str):
                return None
            namespace, _, _ = tag.partition("}")
            ns_uri = namespace.removeprefix("{") if namespace.startswith("{") else ""
            return ns_uri, local_name(tag)
    except (ET.ParseError, UnicodeDecodeError, ValueError):
        return None
    return None


def is_native_sec_xml(
    raw_bytes: bytes,
    schema_spec: SecXmlSchemaSpec,
) -> bool:
    """Return whether raw_bytes is well-formed XML matching schema spec."""
    root_info = inspect_sec_xml_root(raw_bytes)
    if root_info is None:
        return False
    ns_uri, tag_name = root_info
    if tag_name not in schema_spec.root_tags:
        return False
    if schema_spec.namespaces and ns_uri not in schema_spec.namespaces:
        return False
    return True


def passthrough_sec_xml(
    raw_bytes: bytes,
    schema_spec: SecXmlSchemaSpec,
) -> HandlerOutput | None:
    """Return HandlerOutput if raw_bytes is native SEC XML matching spec, else None."""
    if not is_native_sec_xml(raw_bytes, schema_spec):
        return None
    return HandlerOutput(
        content=raw_bytes,
        sidecars=(
            HandlerSidecar("unparsed_sections.json", serialize_unparsed_sections(())),
        ),
    )


__all__ = [
    "inspect_sec_xml_root",
    "is_native_sec_xml",
    "passthrough_sec_xml",
]
