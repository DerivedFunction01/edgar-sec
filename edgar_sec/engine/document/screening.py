"""Canonical document identity and inversion screening.

Provides unified screening for candidate primary documents across SGML,
filename, exhibit header, and normalized cover boundaries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from edgar_sec.domain.forms.common.aliases import resolve_alias
from edgar_sec.engine.document.unpacking.streaming import screen_sgml_document_type
from edgar_sec.engine.forms.plugins.exhibit_selection import (
    PROBE_CHAR_BOUND,
    probe_exhibit_header,
)
from edgar_sec.foundation.io import DEFAULT_IO_CHUNK_SIZE

ScreenResult = Literal["form_match", "type_mismatch", "unverifiable"]
ScreenKind = Literal["sgml_type", "filename", "exhibit_header", "html_cover"]

_FORM_TITLE_RE = re.compile(r"(?i)\bFORM\s+([0-9A-Za-z\-]+(?:/A)?)")
_SGML_TYPE_BYTES_RE = re.compile(rb"(?i)<TYPE>\s*([^\r\n<]+)")
_HTML_TAG_BYTES_RE = re.compile(rb"<[^>]{1,256}>")

_SPECIALIZED_XML_MARKERS: dict[str, tuple[tuple[str, ...], ...]] = {
    "3": (
        (b"reporting owner", b"reportingowner", b"reporting person"),
        (b"issuer",),
        (b"relationship of reporting person", b"is director", b"is officer"),
        (b"non-derivative", b"derivative securities", b"table i"),
    ),
    "4": (
        (b"reporting owner", b"reportingowner", b"reporting person"),
        (b"issuer",),
        (b"relationship of reporting person", b"is director", b"is officer"),
        (b"non-derivative", b"derivative securities", b"table i"),
    ),
    "5": (
        (b"reporting owner", b"reportingowner", b"reporting person"),
        (b"issuer",),
        (b"relationship of reporting person", b"is director", b"is officer"),
        (b"non-derivative", b"derivative securities", b"table i"),
    ),
    "144": (
        (b"form 144", b"notice of proposed sale"),
        (b"issuer",),
        (b"securities to be sold", b"proposed sale"),
        (b"signature", b"sign here"),
    ),
    "13D": (
        (b"schedule 13d", b"sc 13d"),
        (b"reporting person", b"reporting persons"),
        (b"issuer", b"name of issuer"),
        (b"item 1", b"source of funds", b"percent of class"),
    ),
    "13G": (
        (b"schedule 13g", b"sc 13g"),
        (b"reporting person", b"reporting persons"),
        (b"issuer", b"name of issuer"),
        (b"item 1", b"source of funds", b"percent of class"),
    ),
}


@dataclass(frozen=True, slots=True)
class CandidateScreen:
    """Outcome of evaluating a candidate primary document."""

    screen_result: ScreenResult
    is_inversion: bool
    screen_kind: ScreenKind
    observed_body_type: str | None
    reason: str


_UNSET: object = object()


def _screen_sgml_type(observed: str | None, expected_family: str) -> CandidateScreen:
    if observed is None:
        return CandidateScreen(
            "unverifiable", False, "sgml_type", None, "sgml_type_unverifiable"
        )
    observed_family = resolve_alias(observed) or observed.strip().upper()
    sgml_result = screen_sgml_document_type(observed_family, expected_family)
    if sgml_result == "form_match":
        return CandidateScreen(
            "form_match", False, "sgml_type", observed, "sgml_type_match"
        )
    if sgml_result == "type_mismatch":
        return CandidateScreen(
            "type_mismatch", True, "sgml_type", observed, "sgml_type_mismatch"
        )
    return CandidateScreen(
        "unverifiable", False, "sgml_type", observed, "sgml_type_unverifiable"
    )


def screen_candidate_document(
    expected_form: str,
    *,
    filename: str | None = None,
    raw_content: bytes | None = None,
    observed_sgml_type: str | None | object = _UNSET,
    normalized_text: str | None = None,
    scan_limit_bytes: int = DEFAULT_IO_CHUNK_SIZE,
) -> CandidateScreen:
    """Screen a candidate primary document for form identity and inversion."""
    expected_family = resolve_alias(expected_form) or expected_form.strip().upper()

    if observed_sgml_type is not _UNSET:
        str_val = observed_sgml_type if isinstance(observed_sgml_type, str) else None
        return _screen_sgml_type(str_val, expected_family)

    if raw_content:
        head = raw_content[:scan_limit_bytes]
        if b"<TYPE>EX-" in head[:2000] or b"<TYPE>GRAPHIC" in head[:2000]:
            return CandidateScreen(
                "type_mismatch", True, "sgml_type", "EXHIBIT", "sgml_exhibit_tag"
            )
        sgml_match = _SGML_TYPE_BYTES_RE.search(head[:2000])
        if sgml_match is not None:
            found_raw = sgml_match.group(1).decode("ascii", errors="ignore").strip()
            sgml_screen = _screen_sgml_type(found_raw, expected_family)
            if sgml_screen.screen_result in {"form_match", "type_mismatch"}:
                return sgml_screen

    if filename is not None:
        leaf = Path(filename).name.lower()
        norm_leaf = leaf.replace("-", "").replace("_", "")
        expected_norm = expected_family.lower().replace("-", "").replace("_", "")
        if leaf.startswith(("ex", "exhibit")) and (
            not expected_norm or not norm_leaf.startswith(expected_norm)
        ):
            return CandidateScreen(
                "type_mismatch", True, "filename", "EXHIBIT", "exhibit_filename"
            )

    if normalized_text is not None:
        lines = tuple(normalized_text.splitlines()[:25])
        if probe_exhibit_header(normalized_text, lines) is not None:
            return CandidateScreen(
                "type_mismatch",
                True,
                "exhibit_header",
                "EXHIBIT",
                "exhibit_header_detected",
            )

        title_match = _FORM_TITLE_RE.search(normalized_text[:PROBE_CHAR_BOUND])
        if title_match is not None:
            found_raw = title_match.group(1).strip()
            found_family = resolve_alias(found_raw) or found_raw.upper()
            if found_family == expected_family:
                return CandidateScreen(
                    "form_match", False, "html_cover", found_family, "form_title_match"
                )
            return CandidateScreen(
                "type_mismatch",
                True,
                "html_cover",
                found_family,
                "competing_form_title",
            )

    return CandidateScreen(
        "unverifiable", False, "html_cover", None, "unverifiable_cover"
    )


def screen_specialized_xml_source(
    expected_form: str,
    raw_content: bytes,
    *,
    scan_limit_bytes: int = DEFAULT_IO_CHUNK_SIZE,
) -> CandidateScreen:
    expected_family = resolve_alias(expected_form) or expected_form.strip().upper()
    markers = _SPECIALIZED_XML_MARKERS.get(expected_family)
    if markers is None:
        return CandidateScreen(
            "unverifiable", False, "html_cover", None, "no_form_structure_policy"
        )

    source = raw_content[:scan_limit_bytes].lower()
    if expected_family in {"3", "4", "5"} and b"ownershipdocument" in source:
        return CandidateScreen(
            "form_match", False, "html_cover", expected_family, "native_ownership_xml"
        )
    if expected_family in {"144", "13D", "13G"} and b"edgarsubmission" in source:
        form_marker = expected_family.encode("ascii").lower()
        if form_marker in source:
            return CandidateScreen(
                "form_match", False, "html_cover", expected_family, "native_form_xml"
            )

    text = _HTML_TAG_BYTES_RE.sub(b" ", source)
    text = b" ".join(text.split())
    matched = tuple(any(marker in text for marker in group) for group in markers)
    if expected_family in {"3", "4", "5"}:
        matches_form = matched[0] and sum(matched) >= 2
    elif expected_family == "144":
        matches_form = matched[0] and sum(matched[1:]) >= 1
    else:
        matches_form = matched[0] and matched[1] and sum(matched[2:]) >= 1
    if matches_form:
        return CandidateScreen(
            "form_match", False, "html_cover", expected_family, "form_structure_match"
        )
    return CandidateScreen(
        "unverifiable",
        False,
        "html_cover",
        None,
        "form_structure_markers_missing",
    )


__all__ = [
    "CandidateScreen",
    "ScreenKind",
    "ScreenResult",
    "screen_candidate_document",
    "screen_specialized_xml_source",
]
