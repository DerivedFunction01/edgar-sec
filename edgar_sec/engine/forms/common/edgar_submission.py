"""Shared header parsing for edgarSubmission-rooted SEC XML forms."""

from __future__ import annotations

from dataclasses import dataclass
import xml.etree.ElementTree as ET

from edgar_sec.engine.forms.common.extraction import (
    find_child_element,
    find_deep_elements,
    local_name,
    xml_element_text_or_none,
)


@dataclass(frozen=True, slots=True)
class EdgarHeader:
    """Header facts common to every edgarSubmission-rooted form family."""

    submission_type: str | None
    live_test_flag: str | None
    filer_ciks: tuple[str, ...]
    contact_name: str | None
    contact_email: str | None


def edgar_submission_root(raw_bytes: bytes) -> ET.Element | None:
    """Parsed root element when the payload is an edgarSubmission document."""
    try:
        root = ET.fromstring(raw_bytes)
    except ET.ParseError:
        return None
    if local_name(root.tag) != "edgarSubmission":
        return None
    return root


def parse_edgar_header(raw_bytes: bytes) -> EdgarHeader | None:
    """Extract the header block; None when the payload is not a submission."""
    root = edgar_submission_root(raw_bytes)
    if root is None:
        return None
    return edgar_header_from_root(root)


def edgar_header_from_root(root: ET.Element) -> EdgarHeader | None:
    """Extract the header block from a parsed edgarSubmission root."""
    if local_name(root.tag) != "edgarSubmission":
        return None
    header = find_child_element(root, "headerData") or root
    filer_info = find_child_element(header, "filerInfo")
    scope = filer_info if filer_info is not None else header
    ciks = tuple(
        text
        for text in (
            xml_element_text_or_none(e) for e in find_deep_elements(scope, "filerCik")
        )
        if text
    )
    contact = find_child_element(scope, "contact")
    live = (
        xml_element_text_or_none(find_child_element(scope, "liveTestFlag"))
        or xml_element_text_or_none(find_child_element(header, "liveTestFlag"))
        or xml_element_text_or_none(find_child_element(header, "testOrLive"))
    )
    return EdgarHeader(
        submission_type=xml_element_text_or_none(
            find_child_element(header, "submissionType")
        ),
        live_test_flag=live,
        filer_ciks=ciks,
        contact_name=xml_element_text_or_none(
            find_child_element(contact, "contactName")
        )
        if contact is not None
        else None,
        contact_email=(
            xml_element_text_or_none(find_child_element(contact, "contactEmail"))
            if contact is not None
            else None
        ),
    )


__all__ = [
    "EdgarHeader",
    "edgar_header_from_root",
    "edgar_submission_root",
    "parse_edgar_header",
]
