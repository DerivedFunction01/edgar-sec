"""Canonical XML renderer for SEC Form N-PX filings."""

from __future__ import annotations

from typing import TYPE_CHECKING
import xml.etree.ElementTree as ET

from edgar_sec.domain.forms.families.form_npx.models import (
    FormNPxDocument,
    ProxyVoteRow,
)
from edgar_sec.domain.forms.families.form_npx.taxonomy import (
    N_PX_NAMESPACE,
    N_PX_VOTE_NAMESPACE,
    N_PX_XML_SPEC,
)
from edgar_sec.engine.document_processing.outputs import HandlerOutput
from edgar_sec.engine.forms.common.native_xml import passthrough_sec_xml
from edgar_sec.engine.forms.common.xml_builder import (
    add_text_element,
    canonical_xml_output,
    child_element,
    root_element,
)
from edgar_sec.engine.forms.form_npx.ascii_parser import parse_npx_text
from edgar_sec.engine.forms.form_npx.xml_parser import parse_npx_xml

if TYPE_CHECKING:
    from edgar_sec.engine.document_processing.registry import HandlerContext

_COMMON_NS = "http://www.sec.gov/edgar/common"


def _q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def _add_vote_row(parent: ET.Element, row: ProxyVoteRow) -> None:
    ns = N_PX_VOTE_NAMESPACE
    entry = child_element(parent, _q(ns, "proxyTable"))
    add_text_element(entry, _q(ns, "issuerName"), row.issuer_name)
    if row.cusip is not None:
        add_text_element(entry, _q(ns, "cusip"), row.cusip)
    if row.isin is not None:
        add_text_element(entry, _q(ns, "isin"), row.isin)
    if row.figi is not None:
        add_text_element(entry, _q(ns, "figi"), row.figi)
    add_text_element(entry, _q(ns, "meetingDate"), row.meeting_date)
    add_text_element(entry, _q(ns, "voteDescription"), row.vote_description)
    if row.category_types:
        categories = child_element(entry, _q(ns, "voteCategories"))
        for category_type in row.category_types:
            category = child_element(categories, _q(ns, "voteCategory"))
            add_text_element(category, _q(ns, "categoryType"), category_type)
    if row.vote_source is not None:
        add_text_element(entry, _q(ns, "voteSource"), row.vote_source)
    if row.shares_voted is not None:
        add_text_element(entry, _q(ns, "sharesVoted"), row.shares_voted)
    if row.shares_on_loan is not None:
        add_text_element(entry, _q(ns, "sharesOnLoan"), row.shares_on_loan)
    if row.how_voted:
        vote = child_element(entry, _q(ns, "vote"))
        for how in row.how_voted:
            record = child_element(vote, _q(ns, "voteRecord"))
            add_text_element(record, _q(ns, "howVoted"), how)


def _build_vote_table(doc: FormNPxDocument) -> HandlerOutput:
    ET.register_namespace("inf", N_PX_VOTE_NAMESPACE)
    root = root_element(_q(N_PX_VOTE_NAMESPACE, "proxyVoteTable"))
    for row in doc.vote_rows:
        _add_vote_row(root, row)
    return canonical_xml_output(root)


def build_npx_xml(doc: FormNPxDocument) -> HandlerOutput:
    """Serialize a FormNPxDocument into the canonical XML envelope."""
    has_cover = bool(
        doc.submission_type
        or doc.reporting_person_name
        or doc.report_type
        or doc.period_of_report
    )
    if not has_cover:
        return _build_vote_table(doc)
    ET.register_namespace("", N_PX_NAMESPACE)
    ET.register_namespace("com", _COMMON_NS)
    ns = N_PX_NAMESPACE
    root = root_element(_q(ns, "edgarSubmission"))
    header = child_element(root, _q(ns, "headerData"))
    add_text_element(header, _q(ns, "submissionType"), doc.submission_type)
    filer_info = child_element(header, _q(ns, "filerInfo"))
    if doc.registrant_type is not None:
        add_text_element(filer_info, _q(ns, "registrantType"), doc.registrant_type)
    if doc.investment_company_type is not None:
        add_text_element(
            filer_info, _q(ns, "investmentCompanyType"), doc.investment_company_type
        )
    if doc.period_of_report is not None:
        add_text_element(filer_info, _q(ns, "periodOfReport"), doc.period_of_report)
    form_data = child_element(root, _q(ns, "formData"))
    cover = child_element(form_data, _q(ns, "coverPage"))
    if doc.year_or_quarter is not None:
        add_text_element(cover, _q(ns, "yearOrQuarter"), doc.year_or_quarter)
    if doc.report_calendar_year is not None:
        add_text_element(cover, _q(ns, "reportCalendarYear"), doc.report_calendar_year)
    if doc.reporting_person_name is not None:
        person = child_element(cover, _q(ns, "reportingPerson"))
        add_text_element(person, _q(ns, "name"), doc.reporting_person_name)
    if doc.report_type is not None:
        info = child_element(cover, _q(ns, "reportInfo"))
        add_text_element(info, _q(ns, "reportType"), doc.report_type)
    if doc.file_number is not None:
        add_text_element(cover, _q(ns, "fileNumber"), doc.file_number)
    if doc.lei_number is not None:
        add_text_element(cover, _q(ns, "leiNumber"), doc.lei_number)
    if doc.series_count is not None:
        series_page = child_element(form_data, _q(ns, "seriesPage"))
        add_text_element(series_page, _q(ns, "seriesCount"), str(doc.series_count))
    if doc.other_included_managers_count is not None:
        summary_page = child_element(form_data, _q(ns, "summaryPage"))
        add_text_element(
            summary_page,
            _q(ns, "otherIncludedManagersCount"),
            str(doc.other_included_managers_count),
        )
    if doc.vote_rows:
        table = child_element(form_data, _q(N_PX_VOTE_NAMESPACE, "proxyVoteTable"))
        for row in doc.vote_rows:
            _add_vote_row(table, row)
    return canonical_xml_output(root)


def render_npx_to_xml(
    raw_bytes: bytes,
    context: HandlerContext | None = None,
) -> HandlerOutput:
    """Render Form N-PX raw input to canonical XML with pass-through."""
    passthrough = passthrough_sec_xml(raw_bytes, N_PX_XML_SPEC)
    if passthrough is not None:
        return passthrough
    stripped = raw_bytes.lstrip()
    if stripped.startswith(b"<") and (
        b"edgarSubmission" in raw_bytes[:2048] or b"proxyVoteTable" in raw_bytes[:2048]
    ):
        doc = parse_npx_xml(raw_bytes)
    else:
        doc = parse_npx_text(raw_bytes)
    return build_npx_xml(doc)


__all__ = ["build_npx_xml", "render_npx_to_xml"]
