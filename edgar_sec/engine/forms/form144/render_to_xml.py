"""Canonical XML envelope generation for SEC Form 144 filings."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
import xml.etree.ElementTree as ET

from edgar_sec.domain.forms.families.form144.models import (
    Form144Document,
    ProposedSaleItem,
    TableISecurityItem,
    TableIISecuritySoldItem,
)
from edgar_sec.engine.forms.form144.grid_tables import (
    parse_table_i_rows,
    parse_table_ii_rows,
)
from edgar_sec.engine.forms.form144.cover_parser import parse_cover_box_1_2
from edgar_sec.engine.forms.form144.metadata_parser import (
    parse_remarks,
    parse_signatures,
)
from edgar_sec.engine.forms.form144.sale_parser import parse_proposed_sale_box_3
from edgar_sec.engine.document.html.cleaner import (
    strip_decorative_presentation_attributes,
)
from edgar_sec.engine.forms.form144.sections import (
    Form144Sections,
    partition_form144_tables,
)

if TYPE_CHECKING:
    from edgar_sec.engine.document_processing.registry import HandlerContext

_XML_DECL_RE = re.compile(r"^\s*<\?xml", re.IGNORECASE)
_EDGAR_SUBMISSION_RE = re.compile(
    r"<\s*(?:edgarSubmission|noticeOfProposedSaleOfSecurities)", re.IGNORECASE
)


def _add_text_elem(
    parent: ET.Element, tag: str, text: str | int | float | None
) -> ET.Element:
    elem = ET.SubElement(parent, tag)
    if text is not None:
        elem.text = str(text)
    return elem


def _build_issuer_xml(form_data: ET.Element, doc: Form144Document) -> None:
    issuer_el = ET.SubElement(form_data, "issuerInfo")
    if doc.issuer.cik:
        _add_text_elem(issuer_el, "issuerCik", doc.issuer.cik)
    if doc.issuer.name:
        _add_text_elem(issuer_el, "issuerName", doc.issuer.name)
    if doc.issuer.sec_file_number:
        _add_text_elem(issuer_el, "secFileNumber", doc.issuer.sec_file_number)

    addr_el = ET.SubElement(issuer_el, "issuerAddress")
    if doc.issuer.street1:
        _add_text_elem(addr_el, "com:street1", doc.issuer.street1)
    if doc.issuer.street2:
        _add_text_elem(addr_el, "com:street2", doc.issuer.street2)
    if doc.issuer.city:
        _add_text_elem(addr_el, "com:city", doc.issuer.city)
    if doc.issuer.state_or_country:
        _add_text_elem(addr_el, "com:stateOrCountry", doc.issuer.state_or_country)
    if doc.issuer.zip_code:
        _add_text_elem(addr_el, "com:zipCode", doc.issuer.zip_code)

    if doc.issuer.contact_phone:
        _add_text_elem(issuer_el, "issuerContactPhone", doc.issuer.contact_phone)

    if doc.reporting_person.name:
        _add_text_elem(
            issuer_el,
            "nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold",
            doc.reporting_person.name,
        )

    if doc.reporting_person.relationships:
        rels_el = ET.SubElement(issuer_el, "relationshipsToIssuer")
        for rel in doc.reporting_person.relationships:
            _add_text_elem(rels_el, "relationshipToIssuer", rel)


def _build_securities_information_xml(
    form_data: ET.Element, item: ProposedSaleItem
) -> None:
    sec_el = ET.SubElement(form_data, "securitiesInformation")
    if item.class_title:
        _add_text_elem(sec_el, "securitiesClassTitle", item.class_title)

    if item.broker and item.broker.name:
        broker_el = ET.SubElement(sec_el, "brokerOrMarketmakerDetails")
        _add_text_elem(broker_el, "name", item.broker.name)
        addr_el = ET.SubElement(broker_el, "address")
        if item.broker.street1:
            _add_text_elem(addr_el, "com:street1", item.broker.street1)
        if item.broker.street2:
            _add_text_elem(addr_el, "com:street2", item.broker.street2)
        if item.broker.city:
            _add_text_elem(addr_el, "com:city", item.broker.city)
        if item.broker.state_or_country:
            _add_text_elem(addr_el, "com:stateOrCountry", item.broker.state_or_country)
        if item.broker.zip_code:
            _add_text_elem(addr_el, "com:zipCode", item.broker.zip_code)

    if item.units_to_be_sold is not None:
        val = (
            int(item.units_to_be_sold)
            if isinstance(item.units_to_be_sold, int)
            or (
                isinstance(item.units_to_be_sold, float)
                and item.units_to_be_sold.is_integer()
            )
            else item.units_to_be_sold
        )
        _add_text_elem(sec_el, "noOfUnitsSold", val)
    if item.aggregate_market_value is not None:
        val = (
            int(item.aggregate_market_value)
            if item.aggregate_market_value.is_integer()
            else f"{item.aggregate_market_value:.2f}"
        )
        _add_text_elem(sec_el, "aggregateMarketValue", val)
    if item.units_outstanding is not None:
        val = (
            int(item.units_outstanding)
            if isinstance(item.units_outstanding, int)
            or (
                isinstance(item.units_outstanding, float)
                and item.units_outstanding.is_integer()
            )
            else item.units_outstanding
        )
        _add_text_elem(sec_el, "noOfUnitsOutstanding", val)
    if item.approx_sale_date:
        _add_text_elem(sec_el, "approxSaleDate", item.approx_sale_date)
    if item.exchange_name:
        _add_text_elem(sec_el, "securitiesExchangeName", item.exchange_name)


def _build_table_i_xml(
    form_data: ET.Element, items: tuple[TableISecurityItem, ...]
) -> None:
    for item in items:
        row_el = ET.SubElement(form_data, "securitiesToBeSold")
        if item.class_title:
            _add_text_elem(row_el, "securitiesClassTitle", item.class_title)
        if item.acquired_date:
            _add_text_elem(row_el, "acquiredDate", item.acquired_date)
        if item.nature_of_acquisition:
            _add_text_elem(
                row_el, "natureOfAcquisitionTransaction", item.nature_of_acquisition
            )
        if item.donor_or_seller_name:
            _add_text_elem(
                row_el, "nameOfPersonfromWhomAcquired", item.donor_or_seller_name
            )
        _add_text_elem(row_el, "isGiftTransaction", "Y" if item.is_gift else "N")
        if item.amount_acquired is not None:
            val = (
                int(item.amount_acquired)
                if isinstance(item.amount_acquired, int)
                or (
                    isinstance(item.amount_acquired, float)
                    and item.amount_acquired.is_integer()
                )
                else item.amount_acquired
            )
            _add_text_elem(row_el, "amountOfSecuritiesAcquired", val)
        if item.payment_date:
            _add_text_elem(row_el, "paymentDate", item.payment_date)
        if item.nature_of_payment:
            _add_text_elem(row_el, "natureOfPayment", item.nature_of_payment)


def _build_table_ii_xml(
    form_data: ET.Element,
    nothing_to_report: bool,
    items: tuple[TableIISecuritySoldItem, ...],
) -> None:
    if nothing_to_report or not items:
        _add_text_elem(
            form_data, "nothingToReportFlagOnSecuritiesSoldInPast3Months", "Y"
        )
        return

    _add_text_elem(form_data, "nothingToReportFlagOnSecuritiesSoldInPast3Months", "N")
    for item in items:
        row_el = ET.SubElement(form_data, "securitiesSoldInPast3Months")
        if item.seller_name or item.seller_address:
            seller_el = ET.SubElement(row_el, "sellerDetails")
            if item.seller_name:
                _add_text_elem(seller_el, "name", item.seller_name)
            if item.seller_address:
                addr_el = ET.SubElement(seller_el, "address")
                _add_text_elem(addr_el, "com:street1", item.seller_address)
        if item.class_title:
            _add_text_elem(row_el, "securitiesClassTitle", item.class_title)
        if item.sale_date:
            _add_text_elem(row_el, "saleDate", item.sale_date)
        if item.amount_sold is not None:
            val = (
                int(item.amount_sold)
                if isinstance(item.amount_sold, int)
                or (
                    isinstance(item.amount_sold, float)
                    and item.amount_sold.is_integer()
                )
                else item.amount_sold
            )
            _add_text_elem(row_el, "amountOfSecuritiesSold", val)
        if item.gross_proceeds is not None:
            val = (
                int(item.gross_proceeds)
                if item.gross_proceeds.is_integer()
                else f"{item.gross_proceeds:.2f}"
            )
            _add_text_elem(row_el, "grossProceeds", val)


def _build_signature_xml(form_data: ET.Element, doc: Form144Document) -> None:
    if not doc.signature:
        return
    sig_el = ET.SubElement(form_data, "noticeSignature")
    if doc.signature.notice_date:
        _add_text_elem(sig_el, "noticeDate", doc.signature.notice_date)
    if doc.signature.plan_adoption_dates:
        plans_el = ET.SubElement(sig_el, "planAdoptionDates")
        for pd in doc.signature.plan_adoption_dates:
            _add_text_elem(plans_el, "planAdoptionDate", pd)
    if doc.signature.signature:
        _add_text_elem(sig_el, "signature", doc.signature.signature)


def _build_unparsed_sections_xml(root: ET.Element, sections: Form144Sections) -> None:
    unparsed_nodes = list(sections.unparsed)
    if not unparsed_nodes:
        return
    container = ET.SubElement(root, "unparsedSections")
    for sec in unparsed_nodes:
        unparsed_el = ET.SubElement(container, "unparsedSection")
        unparsed_el.attrib["tableIndex"] = str(sec.table_index)
        unparsed_el.attrib["role"] = str(sec.role)
        raw_html = getattr(sec.raw_node, "html", None)
        raw_str = raw_html() if callable(raw_html) else str(raw_html or "")
        unparsed_el.text = strip_decorative_presentation_attributes(raw_str)


def build_canonical_form144_xml(
    doc: Form144Document, sections: Form144Sections | None = None
) -> bytes:
    """Serialize Form144Document into canonical SEC XML envelope bytes."""
    root = ET.Element(
        "edgarSubmission",
        {
            "xmlns": "http://www.sec.gov/edgar/ownership",
            "xmlns:com": "http://www.sec.gov/edgar/common",
        },
    )
    header = ET.SubElement(root, "headerData")
    _add_text_elem(header, "submissionType", "144")

    form_data = ET.SubElement(root, "formData")
    _build_issuer_xml(form_data, doc)
    _build_securities_information_xml(form_data, doc.proposed_sale)
    _build_table_i_xml(form_data, doc.securities_to_be_sold)
    _build_table_ii_xml(
        form_data,
        doc.nothing_to_report_past_3_months,
        doc.securities_sold_past_3_months,
    )

    if doc.remarks:
        _add_text_elem(form_data, "remarks", doc.remarks)

    _build_signature_xml(form_data, doc)
    if sections:
        _build_unparsed_sections_xml(root, sections)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def render_form144_to_xml(
    raw_bytes: bytes, context: HandlerContext | None = None
) -> bytes:
    """Render Form 144 document bytes to canonical XML."""
    prefix = raw_bytes[:1000].decode("utf-8", errors="ignore")
    if _XML_DECL_RE.search(prefix) or _EDGAR_SUBMISSION_RE.search(prefix):
        try:
            tree = ET.fromstring(raw_bytes)
            return ET.tostring(tree, encoding="utf-8", xml_declaration=True)
        except ET.ParseError:
            pass

    text = raw_bytes.decode("utf-8", errors="ignore")
    sections = partition_form144_tables(text)

    issuer, seller = parse_cover_box_1_2(sections.cover_box_1_2)
    proposed = parse_proposed_sale_box_3(sections.proposed_sale_box_3)
    table_i = parse_table_i_rows(sections.table_i)
    nothing_to_report, table_ii = parse_table_ii_rows(sections.table_ii)
    sig = parse_signatures(sections.signatures, full_text=text)

    doc = Form144Document(
        issuer=issuer,
        reporting_person=seller,
        proposed_sale=proposed,
        securities_to_be_sold=tuple(table_i),
        nothing_to_report_past_3_months=nothing_to_report,
        securities_sold_past_3_months=tuple(table_ii),
        remarks=parse_remarks(sections.remarks),
        signature=sig,
    )
    return build_canonical_form144_xml(doc, sections=sections)


__all__ = [
    "build_canonical_form144_xml",
    "render_form144_to_xml",
]
