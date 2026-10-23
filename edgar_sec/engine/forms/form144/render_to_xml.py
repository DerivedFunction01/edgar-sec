"""Canonical XML envelope generation for SEC Form 144 filings."""

from __future__ import annotations

from dataclasses import replace
import re
from typing import TYPE_CHECKING
import xml.etree.ElementTree as ET

from edgar_sec.domain.forms.families.form144.models import (
    Form144Document,
    ProposedSaleItem,
    TableISecurityItem,
    TableIISecuritySoldItem,
)
from edgar_sec.domain.taxonomy.jurisdictions import EDGAR_JURISDICTION_CODES
from edgar_sec.engine.forms.form144.securities import (
    parse_table_i_rows,
    parse_table_ii_rows,
)
from edgar_sec.engine.forms.form144.cover_parser import parse_cover_box_1_2
from edgar_sec.engine.forms.form144.metadata_parser import (
    parse_remarks,
    parse_signatures,
)
from edgar_sec.engine.forms.form144.sale_parser import parse_proposed_sale_box_3
from edgar_sec.engine.document.html.tree import parse_html
from edgar_sec.engine.document_processing.outputs import HandlerOutput, HandlerSidecar
from edgar_sec.engine.forms.common.dates import (
    external_reference_year,
    normalize_iso_date,
    resolve_reference_year,
)
from edgar_sec.engine.forms.common.extraction import (
    FieldKind,
    FieldSpec,
    add_field_element,
    extract_value,
    format_field_value,
)
from edgar_sec.engine.forms.common.row_extraction import normalize_row_record
from edgar_sec.engine.forms.common.unparsed import serialize_unparsed_sections
from edgar_sec.engine.forms.form144.row_specs import (
    FORM144_PROPOSED_SALE_ROW_SPEC,
    FORM144_TABLE_I_ROW_SPEC,
    FORM144_TABLE_II_ROW_SPEC,
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
    elem = ET.Element(tag)
    if text is not None:
        elem.text = str(text)
        parent.append(elem)
    return elem


def _xml_date(value: str | None, reported_year: int | None) -> str | None:
    canonical = normalize_iso_date(value, reported_year)
    return format_field_value(
        canonical,
        FieldSpec("date", FieldKind.DATE, date_lexeme="MDY"),
    )


def _canonicalize_dates(
    doc: Form144Document,
    reference_year: int | None,
) -> tuple[Form144Document, tuple[dict[str, object], ...]]:
    unresolved: list[dict[str, object]] = []

    def normalize(value: str | None, path: str) -> str | None:
        result = extract_value(
            value,
            FieldSpec(path, FieldKind.DATE),
            reference_year=reference_year,
        )
        if record := result.unresolved_record():
            unresolved.append(record)
        return result.value

    def normalize_jurisdiction(value: str | None, path: str) -> str | None:
        result = extract_value(
            value,
            FieldSpec(
                path,
                FieldKind.JURISDICTION,
                allowed_values=EDGAR_JURISDICTION_CODES,
            ),
        )
        if record := result.unresolved_record():
            unresolved.append(record)
        return result.value

    def normalize_rows(record, spec, prefix: str):
        normalized, evidence = normalize_row_record(
            record,
            spec,
            reference_year=reference_year,
            path_prefix=prefix,
        )
        unresolved.extend(evidence.evidence())
        return normalized

    proposed = normalize_rows(
        doc.proposed_sale, FORM144_PROPOSED_SALE_ROW_SPEC, "proposed_sale."
    )
    issuer = replace(
        doc.issuer,
        state_or_country=normalize_jurisdiction(
            doc.issuer.state_or_country, "issuer.state_or_country"
        ),
    )
    reporting_person = replace(
        doc.reporting_person,
        state_or_country=normalize_jurisdiction(
            doc.reporting_person.state_or_country, "reporting_person.state_or_country"
        ),
    )
    if proposed.broker is not None:
        proposed = replace(
            proposed,
            broker=replace(
                proposed.broker,
                state_or_country=normalize_jurisdiction(
                    proposed.broker.state_or_country,
                    "proposed_sale.broker.state_or_country",
                ),
            ),
        )
    table_i = tuple(
        normalize_rows(item, FORM144_TABLE_I_ROW_SPEC, f"table_i[{index}].")
        for index, item in enumerate(doc.securities_to_be_sold)
    )
    table_ii = tuple(
        normalize_rows(item, FORM144_TABLE_II_ROW_SPEC, f"table_ii[{index}].")
        for index, item in enumerate(doc.securities_sold_past_3_months)
    )
    signature = doc.signature
    if signature is not None:
        signature = replace(
            signature,
            notice_date=normalize(signature.notice_date, "signature.notice_date"),
            plan_adoption_dates=tuple(
                normalized
                for index, value in enumerate(signature.plan_adoption_dates)
                if (
                    normalized := normalize(
                        value, f"signature.plan_adoption_dates[{index}]"
                    )
                )
            ),
        )
    return (
        replace(
            doc,
            issuer=issuer,
            reporting_person=reporting_person,
            proposed_sale=proposed,
            securities_to_be_sold=table_i,
            securities_sold_past_3_months=table_ii,
            signature=signature,
        ),
        tuple(unresolved),
    )


def _document_dates(doc: Form144Document) -> tuple[str | None, ...]:
    return (
        doc.signature.notice_date if doc.signature else None,
        doc.proposed_sale.approx_sale_date,
        *(item.acquired_date for item in doc.securities_to_be_sold),
        *(item.payment_date for item in doc.securities_to_be_sold),
        *(item.sale_date for item in doc.securities_sold_past_3_months),
        *(doc.signature.plan_adoption_dates if doc.signature else ()),
    )


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


def _row_field(spec, name: str) -> FieldSpec:
    column = spec.column(name)
    if column is None:
        raise KeyError(name)
    return column.field


def _build_securities_information_xml(
    form_data: ET.Element, item: ProposedSaleItem, reported_year: int | None
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

    spec = FORM144_PROPOSED_SALE_ROW_SPEC
    if item.units_to_be_sold is not None:
        add_field_element(
            sec_el,
            _row_field(spec, "units_to_be_sold"),
            str(item.units_to_be_sold),
            reference_year=reported_year,
        )
    if item.aggregate_market_value is not None:
        add_field_element(
            sec_el,
            _row_field(spec, "aggregate_market_value"),
            str(item.aggregate_market_value),
            reference_year=reported_year,
        )
    if item.units_outstanding is not None:
        add_field_element(
            sec_el,
            _row_field(spec, "units_outstanding"),
            str(item.units_outstanding),
            reference_year=reported_year,
        )
    if item.approx_sale_date:
        add_field_element(
            sec_el,
            _row_field(spec, "approx_sale_date"),
            item.approx_sale_date,
            reference_year=reported_year,
        )
    if item.exchange_name:
        _add_text_elem(sec_el, "securitiesExchangeName", item.exchange_name)


def _build_table_i_xml(
    form_data: ET.Element,
    items: tuple[TableISecurityItem, ...],
    reported_year: int | None,
) -> None:
    for item in items:
        row_el = ET.SubElement(form_data, "securitiesToBeSold")
        spec = FORM144_TABLE_I_ROW_SPEC
        if item.class_title:
            _add_text_elem(row_el, "securitiesClassTitle", item.class_title)
        if item.acquired_date:
            add_field_element(
                row_el,
                _row_field(spec, "acquired_date"),
                item.acquired_date,
                reference_year=reported_year,
            )
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
            add_field_element(
                row_el,
                _row_field(spec, "amount_acquired"),
                str(item.amount_acquired),
                reference_year=reported_year,
            )
        if item.payment_date:
            add_field_element(
                row_el,
                _row_field(spec, "payment_date"),
                item.payment_date,
                reference_year=reported_year,
            )
        if item.nature_of_payment:
            _add_text_elem(row_el, "natureOfPayment", item.nature_of_payment)


def _build_table_ii_xml(
    form_data: ET.Element,
    nothing_to_report: bool,
    items: tuple[TableIISecuritySoldItem, ...],
    reported_year: int | None,
) -> None:
    if nothing_to_report or not items:
        _add_text_elem(
            form_data, "nothingToReportFlagOnSecuritiesSoldInPast3Months", "Y"
        )
        return

    _add_text_elem(form_data, "nothingToReportFlagOnSecuritiesSoldInPast3Months", "N")
    for item in items:
        row_el = ET.SubElement(form_data, "securitiesSoldInPast3Months")
        spec = FORM144_TABLE_II_ROW_SPEC
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
            add_field_element(
                row_el,
                _row_field(spec, "sale_date"),
                item.sale_date,
                reference_year=reported_year,
            )
        if item.amount_sold is not None:
            add_field_element(
                row_el,
                _row_field(spec, "amount_sold"),
                str(item.amount_sold),
                reference_year=reported_year,
            )
        if item.gross_proceeds is not None:
            add_field_element(
                row_el,
                _row_field(spec, "gross_proceeds"),
                str(item.gross_proceeds),
                reference_year=reported_year,
            )


def _build_signature_xml(
    form_data: ET.Element, doc: Form144Document, reported_year: int | None
) -> None:
    if not doc.signature:
        return
    sig_el = ET.SubElement(form_data, "noticeSignature")
    if doc.signature.notice_date:
        _add_text_elem(
            sig_el, "noticeDate", _xml_date(doc.signature.notice_date, reported_year)
        )
    if doc.signature.plan_adoption_dates:
        plans_el = ET.SubElement(sig_el, "planAdoptionDates")
        for pd in doc.signature.plan_adoption_dates:
            _add_text_elem(plans_el, "planAdoptionDate", _xml_date(pd, reported_year))
    if doc.signature.signature:
        _add_text_elem(sig_el, "signature", doc.signature.signature)


def _unparsed_records(sections: Form144Sections) -> tuple[dict[str, object], ...]:
    records: list[dict[str, object]] = []
    for section in sections.unparsed:
        content = str(getattr(section.raw_node, "html", ""))
        records.append(
            {
                "role": str(section.role),
                "content_type": "text/html",
                "content": content,
                "table_index": section.table_index,
            }
        )
    return tuple(records)


def build_canonical_form144_xml(
    doc: Form144Document, reference_year: int | None = None
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
    reported_year = reference_year
    _build_issuer_xml(form_data, doc)
    _build_securities_information_xml(form_data, doc.proposed_sale, reported_year)
    _build_table_i_xml(form_data, doc.securities_to_be_sold, reported_year)
    _build_table_ii_xml(
        form_data,
        doc.nothing_to_report_past_3_months,
        doc.securities_sold_past_3_months,
        reported_year,
    )

    if doc.remarks:
        _add_text_elem(form_data, "remarks", doc.remarks)

    _build_signature_xml(form_data, doc, reported_year)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def render_form144_to_xml(
    raw_bytes: bytes, context: HandlerContext | None = None
) -> bytes | HandlerOutput:
    """Render Form 144 document bytes to canonical XML."""
    prefix = raw_bytes[:1000].decode("utf-8", errors="ignore")
    if _XML_DECL_RE.search(prefix) or _EDGAR_SUBMISSION_RE.search(prefix):
        try:
            ET.fromstring(raw_bytes)
            return raw_bytes
        except ET.ParseError:
            pass

    text = raw_bytes.decode("utf-8", errors="ignore")
    report_date = getattr(context, "report_date", None) if context is not None else None
    filing_date = getattr(context, "filing_date", None) if context is not None else None
    external_year = external_reference_year(report_date, filing_date)
    sections = partition_form144_tables(text, external_year)

    issuer, seller = parse_cover_box_1_2(sections.cover_box_1_2)
    proposed = parse_proposed_sale_box_3(
        sections.proposed_sale_box_3, reference_year=external_year
    )
    table_i = parse_table_i_rows(sections.table_i, reference_year=external_year)
    nothing_to_report, table_ii = parse_table_ii_rows(
        sections.table_ii, reference_year=external_year
    )
    sig = parse_signatures(
        sections.signatures,
        full_text=text,
        reference_year=external_year,
        fallback_sections=tuple(sections.unparsed),
        text_lines=tuple(parse_html(text).text().splitlines()),
    )

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
    reference_year = resolve_reference_year(
        report_date,
        filing_date,
        _document_dates(doc),
    )
    doc, unresolved_dates = _canonicalize_dates(doc, reference_year)
    xml_bytes = build_canonical_form144_xml(doc, reference_year)
    records = (*unresolved_dates, *_unparsed_records(sections))
    if records:
        return HandlerOutput(
            content=xml_bytes,
            sidecars=(
                HandlerSidecar(
                    "unparsed_sections.json", serialize_unparsed_sections(records)
                ),
            ),
        )
    return xml_bytes


__all__ = [
    "build_canonical_form144_xml",
    "render_form144_to_xml",
]
