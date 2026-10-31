from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _field_target_exists(root: ET.Element, field_path: str) -> bool:
    current = [root]
    for part in field_path.split("."):
        local_part = part.rsplit(":", 1)[-1]
        index = 1
        if local_part.endswith("]") and "[" in local_part:
            local_part, index_text = local_part.rsplit("[", 1)
            try:
                index = int(index_text[:-1])
            except ValueError:
                return False
        candidates = [
            child
            for parent in current
            for child in parent
            if _local_name(child.tag) == local_part
        ]
        if index < 1 or index > len(candidates):
            return False
        current = [candidates[index - 1]]
    return bool(current)


def _path_parts(field_path: str) -> tuple[str, ...]:
    return tuple(part.rsplit(":", 1)[-1] for part in field_path.split("."))


def _output_field_paths(root: ET.Element) -> list[tuple[str, str]]:
    output: list[tuple[str, str]] = []

    def visit(element: ET.Element, path: tuple[str, ...]) -> None:
        counts: dict[str, int] = {}
        children = list(element)
        for child in children:
            name = _local_name(child.tag)
            counts[name] = counts.get(name, 0) + 1
            part = (
                f"{name}[{counts[name]}]"
                if name in {"reportingPersonInfo", "signaturePerson"}
                else name
            )
            child_path = (*path, part)
            if list(child):
                visit(child, child_path)
            elif (child.text or "").strip():
                normalized = _path_parts(".".join(child_path))
                if normalized[:2] == ("formData", "coverPageHeader") or (
                    len(normalized) > 1
                    and normalized[0] == "formData"
                    and normalized[1]
                    in {
                        "reportingPersons",
                        "items1To7",
                        "items1To10",
                        "signatureInfo",
                    }
                ):
                    output.append((".".join(child_path), (child.text or "").strip()))

    visit(root, ())
    return output


def _span(
    element: ET.Element, start_name: str, end_name: str
) -> tuple[int, int] | None:
    try:
        start = int(element.attrib[start_name])
        end = int(element.attrib[end_name])
    except (KeyError, ValueError):
        return None
    return start, end


def analyze_extraction_provenance(
    root: ET.Element,
    source_text: str | None,
    accession: str,
    *,
    required: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    anomalies: list[dict[str, Any]] = []
    extraction_nodes = [
        node for node in root.iter() if _local_name(node.tag) == "extractionProvenance"
    ]
    unparsed_containers = [
        node for node in root.iter() if _local_name(node.tag) == "unparsedSections"
    ]
    if not extraction_nodes:
        if required:
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "missing_extraction_provenance",
                    "detail": "converted XML has no extraction-to-field mapping",
                }
            )
        return anomalies, None
    if len(extraction_nodes) != 1:
        anomalies.append(
            {
                "accession": accession,
                "kind": "duplicate_extraction_provenance",
                "value": len(extraction_nodes),
                "detail": "converted XML has multiple extraction provenance containers",
            }
        )
    if not unparsed_containers:
        anomalies.append(
            {
                "accession": accession,
                "kind": "missing_unparsed_sections",
                "detail": "converted XML has no residual-text container",
            }
        )

    source_lengths: set[int] = set()
    for container in (*extraction_nodes, *unparsed_containers):
        try:
            source_lengths.add(int(container.attrib["sourceLength"]))
        except (KeyError, ValueError):
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "invalid_provenance_source_length",
                    "detail": f"{_local_name(container.tag)} has no valid sourceLength",
                }
            )
    if len(source_lengths) > 1:
        anomalies.append(
            {
                "accession": accession,
                "kind": "provenance_source_length_mismatch",
                "value": sorted(source_lengths),
                "detail": "provenance containers disagree about normalized source length",
            }
        )
    declared_length = next(iter(source_lengths), None)
    if source_text is not None and declared_length is not None:
        if declared_length != len(source_text):
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "provenance_source_length_mismatch",
                    "value": declared_length,
                    "source_length": len(source_text),
                    "detail": "provenance offsets use a different normalized source length",
                }
            )

    if source_text is None:
        return anomalies, None
    length = len(source_text)
    mapped = bytearray(length)
    unparsed = bytearray(length)
    spans: list[tuple[int, int, str, str]] = []
    extraction_nodes_list = [
        child
        for container in extraction_nodes
        for child in container
        if _local_name(child.tag) == "fieldExtraction"
    ]
    mapped_paths = {
        _path_parts(element.attrib["fieldPath"])
        for element in extraction_nodes_list
        if element.attrib.get("fieldPath")
    }
    for element in extraction_nodes_list:
        path = element.attrib.get("fieldPath", "")
        span = _span(element, "startOffset", "endOffset")
        excerpt = next(
            (
                child.text or ""
                for child in element
                if _local_name(child.tag) == "sourceText"
            ),
            "",
        )
        if not path or span is None:
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "invalid_field_extraction",
                    "field": path,
                    "detail": "extraction mapping lacks a field path or valid offsets",
                }
            )
            continue
        start, end = span
        if not 0 <= start < end <= length:
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "invalid_field_extraction",
                    "field": path,
                    "start_offset": start,
                    "end_offset": end,
                    "detail": "extraction offsets are outside normalized source bounds",
                }
            )
            continue
        if excerpt != source_text[start:end]:
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "field_extraction_text_mismatch",
                    "field": path,
                    "start_offset": start,
                    "end_offset": end,
                    "snippet": excerpt[:240],
                    "detail": "mapped source excerpt differs from the normalized source slice",
                }
            )
        if not _field_target_exists(root, path):
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "field_extraction_target_missing",
                    "field": path,
                    "detail": "mapped XML field does not exist in the rendered document",
                }
            )
        spans.append((start, end, path, element.attrib.get("sharedSourceGroup", "")))
        mapped[start:end] = bytes([1]) * (end - start)

    for path, value in _output_field_paths(root):
        if _path_parts(path) not in mapped_paths:
            anomalies.append(
                {
                    "accession": accession,
                    "kind": "output_field_without_provenance",
                    "field": path,
                    "snippet": value[:240],
                    "detail": "nonempty converted field has no source extraction mapping",
                }
            )

    spans.sort(key=lambda span: (span[0], span[1], span[2]))
    active: list[tuple[int, int, str, str]] = []
    for span in spans:
        start, end, path, group = span
        active = [prior for prior in active if prior[1] > start]
        for prior_start, prior_end, prior_path, prior_group in active:
            if prior_path != path and not (group and group == prior_group):
                anomalies.append(
                    {
                        "accession": accession,
                        "kind": "overlapping_field_extractions",
                        "field": path,
                        "other_field": prior_path,
                        "start_offset": start,
                        "end_offset": min(end, prior_end),
                        "detail": "source span maps to multiple fields without a shared-source declaration",
                    }
                )
        active.append(span)

    for container in unparsed_containers:
        for element in container:
            if _local_name(element.tag) != "unparsedSection":
                continue
            span = _span(element, "startOffset", "endOffset")
            value = element.text or ""
            if span is None:
                anomalies.append(
                    {
                        "accession": accession,
                        "kind": "invalid_unparsed_section",
                        "detail": "unparsed section lacks valid offsets",
                    }
                )
                continue
            start, end = span
            if not 0 <= start < end <= length:
                anomalies.append(
                    {
                        "accession": accession,
                        "kind": "invalid_unparsed_section",
                        "start_offset": start,
                        "end_offset": end,
                        "detail": "unparsed section offsets are outside normalized source bounds",
                    }
                )
                continue
            if value != source_text[start:end]:
                anomalies.append(
                    {
                        "accession": accession,
                        "kind": "unparsed_text_mismatch",
                        "start_offset": start,
                        "end_offset": end,
                        "snippet": value[:240],
                        "detail": "unparsed text differs from the normalized source slice",
                    }
                )
            if any(mapped[start:end]):
                anomalies.append(
                    {
                        "accession": accession,
                        "kind": "unparsed_section_overlaps_extraction",
                        "start_offset": start,
                        "end_offset": end,
                        "detail": "unparsed section overlaps text already assigned to an output field",
                    }
                )
            unparsed[start:end] = bytes([1]) * (end - start)

    nonwhitespace = sum(not char.isspace() for char in source_text)
    mapped_nonwhitespace = sum(
        bool(mapped[index]) and not char.isspace()
        for index, char in enumerate(source_text)
    )
    unparsed_nonwhitespace = sum(
        bool(unparsed[index]) and not char.isspace()
        for index, char in enumerate(source_text)
    )
    uncovered_nonwhitespace = sum(
        not mapped[index] and not unparsed[index] and not char.isspace()
        for index, char in enumerate(source_text)
    )
    if uncovered_nonwhitespace:
        start = next(
            index
            for index, char in enumerate(source_text)
            if not mapped[index] and not unparsed[index] and not char.isspace()
        )
        anomalies.append(
            {
                "accession": accession,
                "kind": "uncovered_source_text",
                "char_count": uncovered_nonwhitespace,
                "snippet": source_text[start : start + 240],
                "detail": "non-whitespace normalized source text is neither mapped nor preserved as unparsed",
            }
        )
    return anomalies, {
        "source_length": length,
        "source_nonwhitespace_characters": nonwhitespace,
        "mapped_nonwhitespace_characters": mapped_nonwhitespace,
        "unparsed_nonwhitespace_characters": unparsed_nonwhitespace,
        "uncovered_nonwhitespace_characters": uncovered_nonwhitespace,
        "field_extraction_count": len(extraction_nodes_list),
    }


__all__ = ["analyze_extraction_provenance"]
