"""Parser for SEC Regulation A XML submissions (1-A / 1-K / 1-Z)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from edgar_sec.domain.forms.families.form_rega.models import RegADocument, RegAKind
from edgar_sec.domain.forms.families.form_rega.taxonomy import kind_of
from edgar_sec.engine.forms.common.edgar_submission import (
    edgar_submission_root,
    parse_edgar_header,
)
from edgar_sec.engine.forms.common.extraction import local_name


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


def _find_path(parent: ET.Element, *tags: str) -> ET.Element | None:
    current: ET.Element | None = parent
    for tag in tags:
        if current is None:
            return None
        current = _find_first(current, tag)
    return current


def _first_deep_text(parent: ET.Element, tag_name: str) -> str | None:
    for elem in parent.iter():
        if local_name(elem.tag) == tag_name:
            text = _text(elem)
            if text:
                return text
    return None


def _all_deep_texts(parent: ET.Element, tag_name: str) -> tuple[str, ...]:
    return tuple(
        text
        for text in (_text(e) for e in parent.iter() if local_name(e.tag) == tag_name)
        if text
    )


def parse_rega_xml(raw_bytes: bytes) -> RegADocument | None:
    """Parse a Reg A XML primary into the review model; None when absent."""
    root = edgar_submission_root(raw_bytes)
    header = parse_edgar_header(raw_bytes)
    if root is None or header is None:
        return None
    kind = kind_of(header.submission_type)
    header_elem = _find_first(root, "headerData")
    if header_elem is None:
        header_elem = root
    form_data = _find_first(root, "formData")
    scope = form_data if form_data is not None else root
    header_ciks = _all_deep_texts(header_elem, "cik")
    filer_ciks = header.filer_ciks or header_ciks
    file_number = (
        _first_deep_text(scope, "commissionFileNumber")
        or _first_deep_text(header_elem, "offeringFileNumber")
        or _first_deep_text(header_elem, "fileNumber")
    )
    tier = None
    total_aggregate = None
    if kind is RegAKind.OFFERING:
        tier = _text(_find_path(scope, "summaryInfo", "indicateTier1Tier2Offering"))
        total_aggregate = _text(
            _find_path(scope, "summaryInfo", "totalAggregateOffering")
        )
    return RegADocument(
        submission_type=header.submission_type,
        kind=kind,
        live_test_flag=header.live_test_flag,
        filer_ciks=filer_ciks,
        issuer_name=_first_deep_text(scope, "issuerName"),
        issuer_cik=_first_deep_text(scope, "cik"),
        commission_file_number=file_number,
        jurisdiction=_first_deep_text(scope, "jurisdictionOrganization"),
        tier=tier,
        total_aggregate_offering=total_aggregate,
        has_summary_block=(
            _find_first(scope, "summaryInfo") is not None
            or _find_first(scope, "summaryInfoOffering") is not None
        ),
        has_certification=_find_first(scope, "certificationSuspension") is not None,
    )


__all__ = ["parse_rega_xml"]
