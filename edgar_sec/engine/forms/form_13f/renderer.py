"""Canonical XML renderer for SEC Form 13F filings."""

from __future__ import annotations

from typing import TYPE_CHECKING
import xml.etree.ElementTree as ET

from edgar_sec.domain.forms.families.form_13f.models import (
    Form13FDocument,
    InfoTableRow,
)
from edgar_sec.domain.forms.families.form_13f.taxonomy import (
    FORM13F_SUBMISSION_NAMESPACE,
    FORM13F_XML_NAMESPACE,
    FORM13F_XML_SPEC,
)
from edgar_sec.engine.document_processing.outputs import HandlerOutput
from edgar_sec.engine.forms.common.native_xml import passthrough_sec_xml
from edgar_sec.engine.forms.common.xml_builder import (
    add_text_element,
    canonical_xml_output,
    child_element,
    root_element,
)
from edgar_sec.engine.forms.form_13f.ascii_parser import parse_form_13f_text
from edgar_sec.engine.forms.form_13f.xml_parser import parse_form_13f_xml

if TYPE_CHECKING:
    from edgar_sec.engine.document_processing.registry import HandlerContext

_COMMON_NS = "http://www.sec.gov/edgar/common"


def _q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def _add_info_table(parent: ET.Element, rows: tuple[InfoTableRow, ...]) -> None:
    table = child_element(parent, _q(FORM13F_XML_NAMESPACE, "informationTable"))
    for row in rows:
        entry = child_element(table, _q(FORM13F_XML_NAMESPACE, "infoTable"))
        _row_elements(entry, row)


def _row_elements(entry: ET.Element, row: InfoTableRow) -> None:
    ns = FORM13F_XML_NAMESPACE
    add_text_element(entry, _q(ns, "nameOfIssuer"), row.name_of_issuer)
    add_text_element(entry, _q(ns, "titleOfClass"), row.title_of_class)
    add_text_element(entry, _q(ns, "cusip"), row.cusip)
    if row.figi is not None:
        add_text_element(entry, _q(ns, "figi"), row.figi)
    if row.value is not None:
        add_text_element(entry, _q(ns, "value"), str(row.value))
    shares = child_element(entry, _q(ns, "shrsOrPrnAmt"))
    if row.shares_or_principal is not None:
        add_text_element(shares, _q(ns, "sshPrnamt"), str(row.shares_or_principal))
    if row.amount_type is not None:
        add_text_element(shares, _q(ns, "sshPrnamtType"), row.amount_type)
    if row.put_call is not None:
        add_text_element(entry, _q(ns, "putCall"), row.put_call)
    if row.investment_discretion is not None:
        add_text_element(
            entry, _q(ns, "investmentDiscretion"), row.investment_discretion
        )
    if row.other_managers is not None:
        add_text_element(entry, _q(ns, "otherManager"), row.other_managers)
    voting = child_element(entry, _q(ns, "votingAuthority"))
    if row.voting_sole is not None:
        add_text_element(voting, _q(ns, "Sole"), str(row.voting_sole))
    if row.voting_shared is not None:
        add_text_element(voting, _q(ns, "Shared"), str(row.voting_shared))
    if row.voting_none is not None:
        add_text_element(voting, _q(ns, "None"), str(row.voting_none))


def _build_submission(doc: Form13FDocument) -> HandlerOutput:
    ET.register_namespace("", FORM13F_SUBMISSION_NAMESPACE)
    ET.register_namespace("com", _COMMON_NS)
    ns = FORM13F_SUBMISSION_NAMESPACE
    root = root_element(_q(ns, "edgarSubmission"))
    header = child_element(root, _q(ns, "headerData"))
    add_text_element(header, _q(ns, "submissionType"), doc.submission_type)
    filer_info = child_element(header, _q(ns, "filerInfo"))
    if doc.live_test_flag is not None:
        add_text_element(filer_info, _q(ns, "liveTestFlag"), doc.live_test_flag)
    if doc.period_of_report is not None:
        add_text_element(filer_info, _q(ns, "periodOfReport"), doc.period_of_report)
    form_data = child_element(root, _q(ns, "formData"))
    cover = child_element(form_data, _q(ns, "coverPage"))
    if doc.report_calendar_or_quarter is not None:
        add_text_element(
            cover, _q(ns, "reportCalendarOrQuarter"), doc.report_calendar_or_quarter
        )
    add_text_element(
        cover, _q(ns, "isAmendment"), "true" if doc.is_amendment else "false"
    )
    if doc.amendment_number is not None:
        add_text_element(cover, _q(ns, "amendmentNo"), str(doc.amendment_number))
    if doc.amendment_type is not None:
        info = child_element(cover, _q(ns, "amendmentInfo"))
        add_text_element(info, _q(ns, "amendmentType"), doc.amendment_type)
    manager = child_element(cover, _q(ns, "filingManager"))
    add_text_element(manager, _q(ns, "name"), doc.manager_name)
    if doc.manager_address is not None:
        address = child_element(manager, _q(ns, "address"))
        addr = doc.manager_address
        add_text_element(address, _q(_COMMON_NS, "street1"), addr.street1)
        if addr.street2 is not None:
            add_text_element(address, _q(_COMMON_NS, "street2"), addr.street2)
        add_text_element(address, _q(_COMMON_NS, "city"), addr.city)
        add_text_element(
            address, _q(_COMMON_NS, "stateOrCountry"), addr.state_or_country
        )
        if addr.zip_code is not None:
            add_text_element(address, _q(_COMMON_NS, "zipCode"), addr.zip_code)
    if doc.report_type is not None:
        add_text_element(cover, _q(ns, "reportType"), doc.report_type)
    if doc.form13f_file_number is not None:
        add_text_element(cover, _q(ns, "form13FFileNumber"), doc.form13f_file_number)
    if doc.crd_number is not None:
        add_text_element(cover, _q(ns, "crdNumber"), doc.crd_number)
    if doc.sec_file_number is not None:
        add_text_element(cover, _q(ns, "secFileNumber"), doc.sec_file_number)
    summary = child_element(form_data, _q(ns, "summaryPage"))
    if doc.other_included_managers_count is not None:
        add_text_element(
            summary,
            _q(ns, "otherIncludedManagersCount"),
            str(doc.other_included_managers_count),
        )
    if doc.table_entry_total is not None:
        add_text_element(summary, _q(ns, "tableEntryTotal"), str(doc.table_entry_total))
    if doc.table_value_total is not None:
        add_text_element(summary, _q(ns, "tableValueTotal"), str(doc.table_value_total))
    if doc.is_confidential_omitted is not None:
        add_text_element(
            summary,
            _q(ns, "isConfidentialOmitted"),
            "true" if doc.is_confidential_omitted else "false",
        )
    if doc.holdings:
        _add_info_table(form_data, doc.holdings)
    return canonical_xml_output(root)


def _build_information_table(doc: Form13FDocument) -> HandlerOutput:
    ET.register_namespace("", FORM13F_XML_NAMESPACE)
    root = root_element(_q(FORM13F_XML_NAMESPACE, "informationTable"))
    for row in doc.holdings:
        entry = child_element(root, _q(FORM13F_XML_NAMESPACE, "infoTable"))
        _row_elements(entry, row)
    return canonical_xml_output(root)


def build_form_13f_xml(doc: Form13FDocument) -> HandlerOutput:
    """Serialize a Form13FDocument into the canonical XML envelope."""
    has_cover = bool(
        doc.submission_type
        or doc.manager_name
        or doc.report_type
        or doc.period_of_report
    )
    if has_cover:
        return _build_submission(doc)
    return _build_information_table(doc)


def render_form_13f_to_xml(
    raw_bytes: bytes,
    context: HandlerContext | None = None,
) -> HandlerOutput:
    """Render Form 13F raw input to canonical XML with pass-through fast path."""
    passthrough = passthrough_sec_xml(raw_bytes, FORM13F_XML_SPEC)
    if passthrough is not None:
        return passthrough
    stripped = raw_bytes.lstrip()
    if stripped.startswith(b"<") and b"informationTable" in raw_bytes[:512]:
        doc = parse_form_13f_xml(raw_bytes)
    elif stripped.startswith(b"<") and b"edgarSubmission" in raw_bytes[:2048]:
        doc = parse_form_13f_xml(raw_bytes)
    else:
        doc = parse_form_13f_text(raw_bytes)
    return build_form_13f_xml(doc)


__all__ = ["build_form_13f_xml", "render_form_13f_to_xml"]
