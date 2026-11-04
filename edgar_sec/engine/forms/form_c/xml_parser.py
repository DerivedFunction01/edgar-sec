"""Parser for SEC Form C XML submissions."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from edgar_sec.domain.forms.families.form_c.models import (
    CIssuer,
    FormCDocument,
)
from edgar_sec.domain.forms.families.form_c.taxonomy import kind_of
from edgar_sec.engine.forms.common.edgar_submission import (
    edgar_header_from_root,
    edgar_submission_root,
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


def _deep_counts(parent: ET.Element, tag_names: frozenset[str]) -> dict[str, int]:
    counts = dict.fromkeys(tag_names, 0)
    for elem in parent.iter():
        name = local_name(elem.tag)
        if name in counts:
            counts[name] += 1
    return counts


def parse_form_c_xml(raw_bytes: bytes) -> FormCDocument | None:
    """Parse a Form C primary into the review model; None when absent."""
    root = edgar_submission_root(raw_bytes)
    header = edgar_header_from_root(root) if root is not None else None
    if root is None or header is None:
        return None
    form_data = _find_first(root, "formData")
    scope = form_data if form_data is not None else root
    deep = _deep_counts(
        scope,
        frozenset({"coIssuerInfo", "progressUpdate", "totalAssetMostRecentFiscalYear"}),
    )
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
        co_issuer_count=deep["coIssuerInfo"],
    )
    offering = _find_first(scope, "offeringInformation")
    return FormCDocument(
        submission_type=header.submission_type,
        kind=kind_of(header.submission_type),
        live_test_flag=header.live_test_flag,
        filer_ciks=header.filer_ciks,
        issuer=issuer,
        has_offering_information=offering is not None,
        has_progress_update=deep["progressUpdate"] > 0,
        has_annual_financials=deep["totalAssetMostRecentFiscalYear"] > 0,
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
