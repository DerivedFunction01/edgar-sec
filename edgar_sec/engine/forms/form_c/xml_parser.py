"""Parser for SEC Form C XML submissions."""

from __future__ import annotations

from edgar_sec.domain.forms.families.form_c.models import (
    CIssuer,
    FormCDocument,
)
from edgar_sec.domain.forms.families.form_c.taxonomy import kind_of
from edgar_sec.engine.forms.common.edgar_submission import (
    edgar_submission_root,
    parse_edgar_header,
)
from edgar_sec.engine.forms.common.extraction import (
    count_deep_elements,
    find_child_element,
    find_element_path,
    has_deep_element,
    xml_element_text_or_none,
)


def parse_form_c_xml(raw_bytes: bytes) -> FormCDocument | None:
    """Parse a Form C primary into the review model; None when absent."""
    root = edgar_submission_root(raw_bytes)
    header = parse_edgar_header(raw_bytes)
    if root is None or header is None:
        return None
    form_data = find_child_element(root, "formData")
    scope = form_data if form_data is not None else root
    issuer_info = find_element_path(scope, "issuerInformation", "issuerInfo")
    legal = (
        find_child_element(issuer_info, "legalStatus")
        if issuer_info is not None
        else None
    )
    issuer = CIssuer(
        name=xml_element_text_or_none(find_child_element(issuer_info, "nameOfIssuer"))
        if issuer_info is not None
        else None,
        commission_cik=(
            xml_element_text_or_none(
                find_element_path(scope, "issuerInformation", "commissionCik")
            )
        ),
        commission_file_number=(
            xml_element_text_or_none(
                find_element_path(scope, "issuerInformation", "commissionFileNumber")
            )
        ),
        legal_status_form=xml_element_text_or_none(
            find_child_element(legal, "legalStatusForm")
        )
        if legal is not None
        else None,
        jurisdiction=(
            xml_element_text_or_none(
                find_child_element(legal, "jurisdictionOrganization")
            )
            if legal is not None
            else None
        ),
        website=xml_element_text_or_none(
            find_child_element(issuer_info, "issuerWebsite")
        )
        if issuer_info is not None
        else None,
        co_issuer_count=count_deep_elements(scope, "coIssuerInfo"),
    )
    offering = find_child_element(scope, "offeringInformation")
    return FormCDocument(
        submission_type=header.submission_type,
        kind=kind_of(header.submission_type),
        live_test_flag=header.live_test_flag,
        filer_ciks=header.filer_ciks,
        issuer=issuer,
        has_offering_information=offering is not None,
        has_progress_update=has_deep_element(scope, "progressUpdate"),
        has_annual_financials=has_deep_element(scope, "totalAssetMostRecentFiscalYear"),
        offering_amount=(
            xml_element_text_or_none(find_child_element(offering, "offeringAmount"))
            if offering is not None
            else None
        ),
        maximum_offering_amount=(
            xml_element_text_or_none(
                find_child_element(offering, "maximumOfferingAmount")
            )
            if offering is not None
            else None
        ),
    )


__all__ = ["parse_form_c_xml"]
