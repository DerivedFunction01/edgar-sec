"""Parser for SEC Form C XML submissions."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from edgar_sec.domain.forms.families.form_c.models import (
    CIssuer,
    FormCDocument,
)
from edgar_sec.domain.forms.families.form_c.taxonomy import kind_of
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


def _has_deep(parent: ET.Element, tag_name: str) -> bool:
    return any(local_name(e.tag) == tag_name for e in parent.iter())


def _count_deep(parent: ET.Element, tag_name: str) -> int:
    return sum(1 for e in parent.iter() if local_name(e.tag) == tag_name)


def parse_form_c_xml(raw_bytes: bytes) -> FormCDocument | None:
    """Parse a Form C primary into the review model; None when absent."""
    root = edgar_submission_root(raw_bytes)
    header = parse_edgar_header(raw_bytes)
    if root is None or header is None:
        return None
    form_data = _find_first(root, "formData")
    scope = form_data if form_data is not None else root
    issuer_info = _find_path(scope, "issuerInformation", "issuerInfo")
    legal = _find_first(issuer_info, "legalStatus") if issuer_info is not None else None
    issuer = CIssuer(
        name=_text(_find_first(issuer_info, "nameOfIssuer"))
        if issuer_info is not None
        else None,
        commission_cik=(_text(_find_path(scope, "issuerInformation", "commissionCik"))),
        commission_file_number=(
            _text(_find_path(scope, "issuerInformation", "commissionFileNumber"))
        ),
        legal_status_form=_text(_find_first(legal, "legalStatusForm"))
        if legal is not None
        else None,
        jurisdiction=(
            _text(_find_first(legal, "jurisdictionOrganization"))
            if legal is not None
            else None
        ),
        website=_text(_find_first(issuer_info, "issuerWebsite"))
        if issuer_info is not None
        else None,
        co_issuer_count=_count_deep(scope, "coIssuerInfo"),
    )
    offering = _find_first(scope, "offeringInformation")
    return FormCDocument(
        submission_type=header.submission_type,
        kind=kind_of(header.submission_type),
        live_test_flag=header.live_test_flag,
        filer_ciks=header.filer_ciks,
        issuer=issuer,
        has_offering_information=offering is not None,
        has_progress_update=_has_deep(scope, "progressUpdate"),
        has_annual_financials=_has_deep(scope, "totalAssetMostRecentFiscalYear"),
        offering_amount=(
            _text(_find_first(offering, "offeringAmount"))
            if offering is not None
            else None
        ),
        maximum_offering_amount=(
            _text(_find_first(offering, "maximumOfferingAmount"))
            if offering is not None
            else None
        ),
    )


__all__ = ["parse_form_c_xml"]
