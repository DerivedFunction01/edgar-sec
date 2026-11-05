"""Parser for SEC Regulation A XML submissions (1-A / 1-K / 1-Z)."""

from __future__ import annotations

from edgar_sec.domain.forms.families.form_rega.models import RegADocument, RegAKind
from edgar_sec.domain.forms.families.form_rega.taxonomy import kind_of
from edgar_sec.engine.forms.common.edgar_submission import (
    edgar_submission_root,
    parse_edgar_header,
)
from edgar_sec.engine.forms.common.extraction import (
    all_deep_texts,
    find_child_element,
    find_element_path,
    first_deep_text,
    xml_element_text_or_none,
)


def parse_rega_xml(raw_bytes: bytes) -> RegADocument | None:
    """Parse a Reg A XML primary into the review model; None when absent."""
    root = edgar_submission_root(raw_bytes)
    header = parse_edgar_header(raw_bytes)
    if root is None or header is None:
        return None
    kind = kind_of(header.submission_type)
    header_elem = find_child_element(root, "headerData")
    if header_elem is None:
        header_elem = root
    form_data = find_child_element(root, "formData")
    scope = form_data if form_data is not None else root
    header_ciks = all_deep_texts(header_elem, "cik")
    filer_ciks = header.filer_ciks or header_ciks
    file_number = (
        first_deep_text(scope, "commissionFileNumber")
        or first_deep_text(header_elem, "offeringFileNumber")
        or first_deep_text(header_elem, "fileNumber")
    )
    tier = None
    total_aggregate = None
    if kind is RegAKind.OFFERING:
        tier = xml_element_text_or_none(
            find_element_path(scope, "summaryInfo", "indicateTier1Tier2Offering")
        )
        total_aggregate = xml_element_text_or_none(
            find_element_path(scope, "summaryInfo", "totalAggregateOffering")
        )
    return RegADocument(
        submission_type=header.submission_type,
        kind=kind,
        live_test_flag=header.live_test_flag,
        filer_ciks=filer_ciks,
        issuer_name=first_deep_text(scope, "issuerName"),
        issuer_cik=first_deep_text(scope, "cik"),
        commission_file_number=file_number,
        jurisdiction=first_deep_text(scope, "jurisdictionOrganization"),
        tier=tier,
        total_aggregate_offering=total_aggregate,
        has_summary_block=(
            find_child_element(scope, "summaryInfo") is not None
            or find_child_element(scope, "summaryInfoOffering") is not None
        ),
        has_certification=find_child_element(scope, "certificationSuspension")
        is not None,
    )


__all__ = ["parse_rega_xml"]
