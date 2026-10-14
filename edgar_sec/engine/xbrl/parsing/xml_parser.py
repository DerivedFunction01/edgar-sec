"""Safe streaming XML parser with namespace handling and bounded memory."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Iterator
import xml.etree.ElementTree as ET


def split_qname(tag: str) -> tuple[str, str]:
    """Split a Clark-notation XML tag into (namespace, local_tag)."""
    if tag.startswith("{"):
        ns, _, local = tag[1:].partition("}")
        return ns, local
    return "", tag


def strip_namespace(tag: str) -> str:
    """Extract local XML element tag name without namespace uri."""
    return split_qname(tag)[1]


def resolve_href_qname(href: str) -> str:
    """Resolve an XBRL xlink:href locator target into a canonical QName."""
    fragment = href.split("#")[-1] if "#" in href else href
    if "_" in fragment:
        prefix, _, name = fragment.partition("_")
        return f"{prefix}:{name}"
    return fragment


def safe_iterparse(
    source: bytes | io.BytesIO | Path | str,
    tag: str | None = None,
    clear_nodes: bool = False,
) -> Iterator[tuple[str, ET.Element]]:
    """Yield (event, elem) pairs while optionally freeing nodes for bounded memory."""
    stream: io.BytesIO | Path | str = (
        io.BytesIO(source) if isinstance(source, bytes) else source
    )
    context = ET.iterparse(stream, events=("end",))
    for event, elem in context:
        local_name = strip_namespace(elem.tag)
        if tag is None or local_name == tag:
            yield event, elem
        if clear_nodes:
            elem.clear()


def safe_parse_root(source: bytes | str) -> ET.Element:
    """Safely parse in-memory XML bytes into an ElementTree root element."""
    payload = source.encode("utf-8") if isinstance(source, str) else source
    return ET.fromstring(payload)
