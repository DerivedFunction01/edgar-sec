"""Canonical XML envelope rendering and pass-through for SEC Form D filings."""

from __future__ import annotations

from typing import TYPE_CHECKING
import xml.etree.ElementTree as ET

from edgar_sec.domain.forms.families.form_d.models import FormDDocument
from edgar_sec.domain.forms.families.form_d.taxonomy import FORMD_XML_SPEC
from edgar_sec.engine.document_processing.outputs import HandlerOutput, HandlerSidecar
from edgar_sec.engine.forms.common.native_xml import passthrough_sec_xml
from edgar_sec.engine.forms.common.unparsed import serialize_unparsed_sections
from edgar_sec.engine.forms.form_d.xml_parser import parse_form_d_xml

if TYPE_CHECKING:
    from edgar_sec.engine.document_processing.registry import HandlerContext


def _add_elem(parent: ET.Element, tag: str, text: str | None) -> ET.Element:
    elem = ET.SubElement(parent, tag)
    if text is not None:
        elem.text = text
    return elem


def build_form_d_xml(doc: FormDDocument) -> HandlerOutput:
    """Build canonical XML bytes and sidecars from FormDDocument model."""
    root = ET.Element("edgarSubmission")
    _add_elem(root, "schemaVersion", doc.schema_version)
    _add_elem(root, "submissionType", doc.submission_type)
    _add_elem(root, "testOrLive", doc.test_or_live)

    pi_elem = ET.SubElement(root, "primaryIssuer")
    _add_elem(pi_elem, "cik", doc.primary_issuer.cik)
    _add_elem(pi_elem, "entityName", doc.primary_issuer.entity_name)
    if doc.primary_issuer.address:
        a_elem = ET.SubElement(pi_elem, "issuerAddress")
        _add_elem(a_elem, "street1", doc.primary_issuer.address.street1)
        _add_elem(a_elem, "street2", doc.primary_issuer.address.street2)
        _add_elem(a_elem, "city", doc.primary_issuer.address.city)
        _add_elem(a_elem, "stateOrCountry", doc.primary_issuer.address.state_or_country)
        _add_elem(
            a_elem,
            "stateOrCountryDescription",
            doc.primary_issuer.address.state_or_country_desc,
        )
        _add_elem(a_elem, "zipCode", doc.primary_issuer.address.zip_code)
    _add_elem(pi_elem, "issuerPhoneNumber", doc.primary_issuer.phone_number)
    _add_elem(pi_elem, "jurisdictionOfInc", doc.primary_issuer.jurisdiction)
    _add_elem(pi_elem, "entityType", doc.primary_issuer.entity_type)

    if doc.related_persons:
        rp_list = ET.SubElement(root, "relatedPersonsList")
        for rp in doc.related_persons:
            info = ET.SubElement(rp_list, "relatedPersonInfo")
            name_elem = ET.SubElement(info, "relatedPersonName")
            _add_elem(name_elem, "firstName", rp.first_name)
            _add_elem(name_elem, "middleName", rp.middle_name)
            _add_elem(name_elem, "lastName", rp.last_name)
            if rp.address:
                ra_elem = ET.SubElement(info, "relatedPersonAddress")
                _add_elem(ra_elem, "street1", rp.address.street1)
                _add_elem(ra_elem, "street2", rp.address.street2)
                _add_elem(ra_elem, "city", rp.address.city)
                _add_elem(ra_elem, "stateOrCountry", rp.address.state_or_country)
                _add_elem(ra_elem, "zipCode", rp.address.zip_code)
            if rp.relationships:
                rel_list = ET.SubElement(info, "relatedPersonRelationshipList")
                for rel in rp.relationships:
                    _add_elem(rel_list, "relationship", rel)
            _add_elem(info, "relationshipClarification", rp.clarification)

    od_elem = ET.SubElement(root, "offeringData")
    if doc.industry_group:
        ig_elem = ET.SubElement(od_elem, "industryGroup")
        _add_elem(ig_elem, "industryGroupType", doc.industry_group)
    if doc.federal_exemptions:
        fe_elem = ET.SubElement(od_elem, "federalExemptionsExclusions")
        for item in doc.federal_exemptions:
            _add_elem(fe_elem, "item", item)
    if doc.offering_amounts:
        amt_elem = ET.SubElement(od_elem, "offeringSalesAmounts")
        if doc.offering_amounts.is_indefinite:
            _add_elem(amt_elem, "totalOfferingAmount", "Indefinite")
            _add_elem(amt_elem, "totalRemaining", "Indefinite")
        else:
            tot = (
                str(int(doc.offering_amounts.total_offering_amount))
                if doc.offering_amounts.total_offering_amount is not None
                else None
            )
            rem = (
                str(int(doc.offering_amounts.total_remaining))
                if doc.offering_amounts.total_remaining is not None
                else None
            )
            _add_elem(amt_elem, "totalOfferingAmount", tot)
            _add_elem(amt_elem, "totalRemaining", rem)
        sold = (
            str(int(doc.offering_amounts.total_amount_sold))
            if doc.offering_amounts.total_amount_sold is not None
            else None
        )
        _add_elem(amt_elem, "totalAmountSold", sold)

    if doc.signatures:
        sb_elem = ET.SubElement(od_elem, "signatureBlock")
        for sig in doc.signatures:
            sig_elem = ET.SubElement(sb_elem, "signature")
            _add_elem(sig_elem, "issuerName", sig.issuer_name)
            _add_elem(sig_elem, "signatureName", sig.signature_name)
            _add_elem(sig_elem, "nameOfSigner", sig.name_of_signer)
            _add_elem(sig_elem, "signatureTitle", sig.signature_title)
            _add_elem(sig_elem, "signatureDate", sig.signature_date)

    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return HandlerOutput(
        content=xml_bytes,
        sidecars=(
            HandlerSidecar("unparsed_sections.json", serialize_unparsed_sections(())),
        ),
    )


def render_form_d_to_xml(
    raw_bytes: bytes,
    context: HandlerContext | None = None,
) -> HandlerOutput:
    """Render Form D raw input to canonical SEC XML with pass-through fast path."""
    passthrough = passthrough_sec_xml(raw_bytes, FORMD_XML_SPEC)
    if passthrough is not None:
        return passthrough
    doc = parse_form_d_xml(raw_bytes)
    return build_form_d_xml(doc)


__all__ = ["build_form_d_xml", "render_form_d_to_xml"]
