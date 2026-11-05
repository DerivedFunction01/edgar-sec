"""Parser for SEC Form N-PX XML documents and proxy vote tables."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from edgar_sec.domain.forms.families.form_npx.models import (
    FormNPxDocument,
    ProxyVoteRow,
)
from edgar_sec.engine.forms.common.extraction import (
    find_child_element,
    find_child_elements,
    local_name,
    xml_element_text_or_none,
)


def _int(elem: ET.Element | None) -> int | None:
    txt = xml_element_text_or_none(elem)
    if not txt:
        return None
    try:
        return int(txt.replace(",", ""))
    except ValueError:
        return None


def _parse_vote_row(row_elem: ET.Element) -> ProxyVoteRow:
    categories_elem = find_child_element(row_elem, "voteCategories")
    category_types: tuple[str, ...] = ()
    if categories_elem is not None:
        category_types = tuple(
            text
            for category in find_child_elements(categories_elem, "voteCategory")
            if (
                text := xml_element_text_or_none(
                    find_child_element(category, "categoryType")
                )
            )
        )
    vote_elem = find_child_element(row_elem, "vote")
    how_voted: tuple[str, ...] = ()
    if vote_elem is not None:
        how_voted = tuple(
            text
            for vote_record in find_child_elements(vote_elem, "voteRecord")
            if (
                text := xml_element_text_or_none(
                    find_child_element(vote_record, "howVoted")
                )
            )
        )
    return ProxyVoteRow(
        issuer_name=xml_element_text_or_none(find_child_element(row_elem, "issuerName"))
        or "",
        meeting_date=xml_element_text_or_none(
            find_child_element(row_elem, "meetingDate")
        )
        or "",
        vote_description=xml_element_text_or_none(
            find_child_element(row_elem, "voteDescription")
        )
        or "",
        cusip=xml_element_text_or_none(find_child_element(row_elem, "cusip")),
        isin=xml_element_text_or_none(find_child_element(row_elem, "isin")),
        figi=xml_element_text_or_none(find_child_element(row_elem, "figi")),
        category_types=category_types,
        vote_source=xml_element_text_or_none(
            find_child_element(row_elem, "voteSource")
        ),
        shares_voted=xml_element_text_or_none(
            find_child_element(row_elem, "sharesVoted")
        ),
        shares_on_loan=xml_element_text_or_none(
            find_child_element(row_elem, "sharesOnLoan")
        ),
        how_voted=how_voted,
    )


def parse_npx_xml(raw_bytes: bytes) -> FormNPxDocument:
    """Parse raw Form N-PX XML bytes into the typed domain model."""
    root = ET.fromstring(raw_bytes)
    if local_name(root.tag) == "proxyVoteTable":
        rows = tuple(
            _parse_vote_row(row) for row in find_child_elements(root, "proxyTable")
        )
        return FormNPxDocument(submission_type="", vote_rows=rows)

    header = find_child_element(root, "headerData")
    filer_info = find_child_element(header, "filerInfo") if header is not None else None
    form_data = find_child_element(root, "formData")
    cover = (
        find_child_element(form_data, "coverPage") if form_data is not None else None
    )
    reporting_person = (
        find_child_element(cover, "reportingPerson") if cover is not None else None
    )
    report_info = find_child_element(cover, "reportInfo") if cover is not None else None
    series_page = (
        find_child_element(form_data, "seriesPage") if form_data is not None else None
    )
    summary_page = (
        find_child_element(form_data, "summaryPage") if form_data is not None else None
    )
    vote_rows: tuple[ProxyVoteRow, ...] = ()
    if form_data is not None:
        for elem in form_data.iter():
            if local_name(elem.tag) == "proxyVoteTable":
                vote_rows = tuple(
                    _parse_vote_row(row)
                    for row in find_child_elements(elem, "proxyTable")
                )
                break
    return FormNPxDocument(
        submission_type=(
            xml_element_text_or_none(find_child_element(header, "submissionType")) or ""
            if header is not None
            else ""
        ),
        vote_rows=vote_rows,
        registrant_type=(
            xml_element_text_or_none(find_child_element(filer_info, "registrantType"))
            if filer_info is not None
            else None
        ),
        period_of_report=(
            xml_element_text_or_none(find_child_element(filer_info, "periodOfReport"))
            if filer_info is not None
            else None
        ),
        year_or_quarter=(
            xml_element_text_or_none(find_child_element(cover, "yearOrQuarter"))
            if cover is not None
            else None
        ),
        report_calendar_year=(
            xml_element_text_or_none(find_child_element(cover, "reportCalendarYear"))
            if cover is not None
            else None
        ),
        reporting_person_name=(
            xml_element_text_or_none(find_child_element(reporting_person, "name"))
            if reporting_person is not None
            else None
        ),
        report_type=(
            xml_element_text_or_none(find_child_element(report_info, "reportType"))
            if report_info is not None
            else None
        ),
        file_number=(
            xml_element_text_or_none(find_child_element(cover, "fileNumber"))
            if cover is not None
            else None
        ),
        lei_number=(
            xml_element_text_or_none(find_child_element(cover, "leiNumber"))
            if cover is not None
            else None
        ),
        investment_company_type=(
            xml_element_text_or_none(
                find_child_element(filer_info, "investmentCompanyType")
            )
            if filer_info is not None
            else None
        ),
        series_count=(
            _int(find_child_element(series_page, "seriesCount"))
            if series_page is not None
            else None
        ),
        other_included_managers_count=(
            _int(find_child_element(summary_page, "otherIncludedManagersCount"))
            if summary_page is not None
            else None
        ),
    )


__all__ = ["parse_npx_xml"]
