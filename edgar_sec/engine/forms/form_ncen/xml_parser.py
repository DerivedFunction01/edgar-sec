"""Parser for SEC Form N-CEN XML documents."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from edgar_sec.domain.forms.families.form_ncen.models import FormNCenDocument
from edgar_sec.engine.forms.common.extraction import (
    count_deep_elements,
    find_child_element,
    find_child_elements,
    xml_element_text_or_none,
)


def parse_ncen_xml(raw_bytes: bytes) -> FormNCenDocument:
    """Parse raw Form N-CEN XML bytes into the typed domain model."""
    root = ET.fromstring(raw_bytes)
    header = find_child_element(root, "headerData")
    filer_info = find_child_element(header, "filerInfo") if header is not None else None
    filer = find_child_element(filer_info, "filer") if filer_info is not None else None
    credentials = (
        find_child_element(filer, "issuerCredentials") if filer is not None else None
    )
    form_data = find_child_element(root, "formData")
    registrant = (
        find_child_element(form_data, "registrantInfo")
        if form_data is not None
        else None
    )
    directors_elem = (
        find_child_element(registrant, "directors") if registrant is not None else None
    )
    director_names: tuple[str, ...] = ()
    if directors_elem is not None:
        director_names = tuple(
            name
            for director in find_child_elements(directors_elem, "director")
            if (
                name := xml_element_text_or_none(
                    find_child_element(director, "directorName")
                )
            )
        )
    series_info = (
        find_child_element(registrant, "securityMatterSeriesInfo")
        if registrant is not None
        else None
    )
    return FormNCenDocument(
        submission_type=(
            xml_element_text_or_none(find_child_element(header, "submissionType")) or ""
            if header is not None
            else ""
        ),
        registrant_name=(
            xml_element_text_or_none(
                find_child_element(registrant, "registrantFullName")
            )
            or ""
            if registrant is not None
            else ""
        ),
        directors=director_names,
        filer_cik=(
            xml_element_text_or_none(find_child_element(credentials, "cik"))
            if credentials is not None
            else None
        ),
        period_of_report=(
            xml_element_text_or_none(find_child_element(filer_info, "periodOfReport"))
            if filer_info is not None
            else None
        ),
        file_number=(
            xml_element_text_or_none(
                find_child_element(registrant, "investmentCompFileNo")
            )
            if registrant is not None
            else None
        ),
        registrant_cik=(
            xml_element_text_or_none(find_child_element(registrant, "registrantCik"))
            if registrant is not None
            else None
        ),
        registrant_lei=(
            xml_element_text_or_none(find_child_element(registrant, "registrantLei"))
            if registrant is not None
            else None
        ),
        classification_type=(
            xml_element_text_or_none(
                find_child_element(registrant, "registrantClassificationType")
            )
            if registrant is not None
            else None
        ),
        city=(
            xml_element_text_or_none(find_child_element(registrant, "registrantcity"))
            if registrant is not None
            else None
        ),
        state=(
            xml_element_text_or_none(find_child_element(registrant, "registrantstate"))
            if registrant is not None
            else None
        ),
        country=(
            xml_element_text_or_none(
                find_child_element(registrant, "registrantcountry")
            )
            if registrant is not None
            else None
        ),
        is_first_filing=(
            xml_element_text_or_none(
                find_child_element(registrant, "isRegistrantFirstFiling")
            )
            if registrant is not None
            else None
        ),
        is_last_filing=(
            xml_element_text_or_none(
                find_child_element(registrant, "isRegistrantLastFiling")
            )
            if registrant is not None
            else None
        ),
        series_count=(
            len(find_child_elements(series_info, "seriesInfo"))
            if series_info is not None
            else 0
        ),
        custodian_count=(
            count_deep_elements(form_data, "custodian") if form_data is not None else 0
        ),
        pricing_service_count=(
            count_deep_elements(form_data, "pricingService")
            if form_data is not None
            else 0
        ),
    )


__all__ = ["parse_ncen_xml"]
