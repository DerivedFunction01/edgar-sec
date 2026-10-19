from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
import xml.etree.ElementTree as ET

from edgar_sec.foundation.serialization import canonical_json

UNPARSED_SECTIONS_FILE = "unparsed_sections.json"


def serialize_unparsed_sections(
    sections: Sequence[Mapping[str, object]],
) -> bytes:
    records = [dict(section) for section in sections]
    if any(
        not isinstance(record.get("role"), str)
        or not isinstance(record.get("content"), str)
        or not isinstance(record.get("content_type"), str)
        or record.get("content_type") not in {"text/plain", "text/html"}
        for record in records
    ):
        raise ValueError("unparsed-section record is invalid")
    return canonical_json({"unparsed_sections": records}).encode("utf-8")


def deserialize_unparsed_sections(data: bytes | str) -> tuple[dict[str, object], ...]:
    try:
        raw = data.decode("utf-8") if isinstance(data, bytes) else data
        payload = json.loads(raw)
    except (TypeError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("unparsed-section sidecar is invalid JSON") from error
    if canonical_json(payload) != raw:
        raise ValueError("unparsed-section sidecar is not canonical JSON")
    if not isinstance(payload, dict) or set(payload) != {"unparsed_sections"}:
        raise ValueError("unparsed-section sidecar has an invalid envelope")
    records = payload["unparsed_sections"]
    if not isinstance(records, list):
        raise ValueError("unparsed-section collection is invalid")
    if any(
        not isinstance(record, dict)
        or not isinstance(record.get("role"), str)
        or not isinstance(record.get("content"), str)
        or not isinstance(record.get("content_type"), str)
        or record.get("content_type") not in {"text/plain", "text/html"}
        for record in records
    ):
        raise ValueError("unparsed-section record is invalid")
    return tuple(records)


def load_unparsed_sections(
    case_directory: str | Path,
    root: ET.Element | None = None,
) -> tuple[dict[str, object], ...]:
    case_root = Path(case_directory)
    sidecar = case_root / "operations" / UNPARSED_SECTIONS_FILE
    if sidecar.exists() or sidecar.is_symlink():
        if (
            case_root.is_symlink()
            or sidecar.parent.is_symlink()
            or sidecar.is_symlink()
            or not sidecar.is_file()
            or not sidecar.resolve(strict=True).is_relative_to(
                case_root.resolve(strict=True)
            )
        ):
            raise ValueError("unparsed-section sidecar is unsafe")
        return deserialize_unparsed_sections(sidecar.read_bytes())
    if root is None:
        return ()
    parents = {child: parent for parent in root.iter() for child in parent}
    records = []
    for element in root.iter():
        name = element.tag.rsplit("}", 1)[-1]
        parent = parents.get(element)
        parent_name = parent.tag.rsplit("}", 1)[-1] if parent is not None else ""
        if name != "unparsedSection" and not (
            name == "section" and parent_name == "unparsedSections"
        ):
            continue
        attributes = element.attrib
        content = "".join(element.itertext()).strip()
        record: dict[str, object] = {
            "role": attributes.get("role", "unparsed"),
            "content_type": (
                "text/html" if "tableIndex" in attributes else "text/plain"
            ),
            "content": content,
        }
        for attr, key in (
            ("tableIndex", "table_index"),
            ("startOffset", "start_offset"),
            ("endOffset", "end_offset"),
        ):
            value = attributes.get(attr)
            if value is not None and value.isdigit():
                record[key] = int(value)
        records.append(record)
    return tuple(records)


__all__ = [
    "UNPARSED_SECTIONS_FILE",
    "deserialize_unparsed_sections",
    "load_unparsed_sections",
    "serialize_unparsed_sections",
]
