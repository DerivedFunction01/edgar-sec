"""Shared scaffolding for the form-family review analyzers and renderers."""

from __future__ import annotations

from collections.abc import Collection, Iterable
from pathlib import Path
import re
from typing import Any
import xml.etree.ElementTree as ET

from edgar_sec.engine.forms.common.fields.extraction import xml_element_text_or_none
from edgar_sec.engine.forms.cover.registrant import (
    parse_registrant_identity,
    previous_content_line,
)
from edgar_sec.engine.tables.ascii_html.model.model import merge_resolved_grids


def empty_report(
    case_dir: Path,
    accession: str,
    anomaly: str,
    core_fields: Iterable[str],
) -> dict[str, Any]:
    """The all-absent review report for a case whose XML never parsed."""
    return {
        "case_id": case_dir.name,
        "accession_number": accession,
        "core_fields": {field: False for field in core_fields},
        "anomalies": [anomaly],
        "review_signals": [
            "xml_missing" if anomaly == "missing_extracted_xml" else "corrupt_xml"
        ],
        "blank_fields": {},
        "unparsed_sections": [],
    }


def core_status(
    doc: Any,
    fields: Iterable[str],
    *,
    none_checked: Collection[str] = (),
) -> dict[str, bool]:
    """Presence map over a document's core fields.

    ``none_checked`` fields count when not None (a stated zero total is
    still a total); every other field counts when truthy.
    """
    return {
        field: (
            getattr(doc, field) is not None
            if field in none_checked
            else bool(getattr(doc, field))
        )
        for field in fields
    }


def qname(ns: str, tag: str) -> str:
    """The Clark-notation qualified name for an XML tag."""
    return f"{{{ns}}}{tag}"


def fields_of(rep: dict[str, Any], form_key: str) -> dict[str, Any]:
    """The per-form field block inside a review case report."""
    return rep.get(form_key, {})


def name_before_label(lines: list[str], label_re: re.Pattern[str]) -> str | None:
    """The registrant name printed on or above a caption label line."""
    for index, line in enumerate(lines):
        match = label_re.search(line)
        if match is None:
            continue
        prefix = line[: match.start()].strip(" ,-(")
        if len(prefix) >= 3 and any(char.isalpha() for char in prefix):
            name = parse_registrant_identity(prefix).name
            if name is not None:
                return name
        cursor = index
        for _ in range(4):
            previous = previous_content_line(lines, cursor)
            if previous is None:
                break
            cursor, text = previous
            if not any(char.isalpha() for char in text):
                continue
            name = parse_registrant_identity(text).name
            if name is not None:
                return name
    return None


def first_group(pattern: re.Pattern[str], text: str) -> str | None:
    """The first capture group of the pattern's first match, if it matches."""
    match = pattern.search(text)
    return match.group(1) if match else None


def element_int(elem: ET.Element | None) -> int | None:
    """The element's text parsed as an int (commas stripped), if it parses."""
    txt = xml_element_text_or_none(elem)
    if not txt:
        return None
    try:
        return int(txt.replace(",", ""))
    except ValueError:
        return None


def merge_sections(existing: Any, incoming: Any) -> Any:
    """Merge two classified sections over the union of their resolved grids."""
    return type(existing)(
        role=existing.role,
        table_index=existing.table_index,
        raw_node=existing.raw_node,
        resolved_grid=merge_resolved_grids(
            existing.resolved_grid, incoming.resolved_grid
        ),
    )


__all__ = [
    "core_status",
    "element_int",
    "empty_report",
    "fields_of",
    "first_group",
    "merge_sections",
    "name_before_label",
    "qname",
]
