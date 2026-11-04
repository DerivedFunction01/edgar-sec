"""Shared header parsing for edgarSubmission-rooted SEC XML forms."""

from __future__ import annotations

from dataclasses import dataclass
import xml.etree.ElementTree as ET

from edgar_sec.engine.forms.common.extraction import local_name


@dataclass(frozen=True, slots=True)
class EdgarHeader:
    """Header facts common to every edgarSubmission-rooted form family."""

    submission_type: str | None
    live_test_flag: str | None
    filer_ciks: tuple[str, ...]
    contact_name: str | None
    contact_email: str | None


def _text(elem: ET.Element | None) -> str | None:
    if elem is None or elem.text is None:
        return None
    val = elem.text.strip()
    return val if val else None


def _find_first(parent: ET.Element, tag_name: str) -> ET.Element | None:
    for child in parent:
        if local_name(child.tag) == tag_name:
            return child
    return None


def _find_all_deep(parent: ET.Element, tag_name: str) -> list[ET.Element]:
    return [e for e in parent.iter() if local_name(e.tag) == tag_name]


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
    header = _find_first(root, "headerData") or root
    filer_info = _find_first(header, "filerInfo")
    scope = filer_info if filer_info is not None else header
    ciks = tuple(
        text for text in (_text(e) for e in _find_all_deep(scope, "filerCik")) if text
    )
    contact = _find_first(scope, "contact")
    live = (
        _text(_find_first(scope, "liveTestFlag"))
        or _text(_find_first(header, "liveTestFlag"))
        or _text(_find_first(header, "testOrLive"))
    )
    return EdgarHeader(
        submission_type=_text(_find_first(header, "submissionType")),
        live_test_flag=live,
        filer_ciks=ciks,
        contact_name=_text(_find_first(contact, "contactName"))
        if contact is not None
        else None,
        contact_email=(
            _text(_find_first(contact, "contactEmail")) if contact is not None else None
        ),
    )


__all__ = ["EdgarHeader", "edgar_submission_root", "parse_edgar_header"]
