"""Canonical XML envelope rendering and pass-through for SEC Form D filings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from edgar_sec.domain.forms.families.form_d.models import FormDDocument
from edgar_sec.domain.forms.families.form_d.taxonomy import FORMD_XML_SPEC
from edgar_sec.engine.document_processing.outputs import HandlerOutput
from edgar_sec.engine.forms.common.native_xml import passthrough_sec_xml
from edgar_sec.engine.forms.common.xml_builder import (
    add_text_element,
    canonical_xml_output,
    child_element,
    root_element,
)
from edgar_sec.engine.forms.form_d.xml_parser import parse_form_d_xml

if TYPE_CHECKING:
    from edgar_sec.engine.document_processing.registry import HandlerContext


def build_form_d_xml(doc: FormDDocument) -> HandlerOutput:
    """Build canonical XML bytes and sidecars from FormDDocument model."""
    root = root_element("edgarSubmission")
    add_text_element(root, "schemaVersion", doc.schema_version)
    add_text_element(root, "submissionType", doc.submission_type)
    add_text_element(root, "testOrLive", doc.test_or_live)

    pi_elem = child_element(root, "primaryIssuer")
    add_text_element(pi_elem, "cik", doc.primary_issuer.cik)
    add_text_element(pi_elem, "entityName", doc.primary_issuer.entity_name)
    if doc.primary_issuer.address:
        a_elem = child_element(pi_elem, "issuerAddress")
        add_text_element(a_elem, "street1", doc.primary_issuer.address.street1)
        add_text_element(a_elem, "street2", doc.primary_issuer.address.street2)
        add_text_element(a_elem, "city", doc.primary_issuer.address.city)
        add_text_element(
            a_elem, "stateOrCountry", doc.primary_issuer.address.state_or_country
        )
        add_text_element(
            a_elem,
            "stateOrCountryDescription",
            doc.primary_issuer.address.state_or_country_desc,
        )
        add_text_element(a_elem, "zipCode", doc.primary_issuer.address.zip_code)
    add_text_element(pi_elem, "issuerPhoneNumber", doc.primary_issuer.phone_number)
    add_text_element(pi_elem, "jurisdictionOfInc", doc.primary_issuer.jurisdiction)
    add_text_element(pi_elem, "entityType", doc.primary_issuer.entity_type)

    if doc.related_persons:
        rp_list = child_element(root, "relatedPersonsList")
        for rp in doc.related_persons:
            info = child_element(rp_list, "relatedPersonInfo")
            name_elem = child_element(info, "relatedPersonName")
            add_text_element(name_elem, "firstName", rp.first_name)
            add_text_element(name_elem, "middleName", rp.middle_name)
            add_text_element(name_elem, "lastName", rp.last_name)
            if rp.address:
                ra_elem = child_element(info, "relatedPersonAddress")
                add_text_element(ra_elem, "street1", rp.address.street1)
                add_text_element(ra_elem, "street2", rp.address.street2)
                add_text_element(ra_elem, "city", rp.address.city)
                add_text_element(ra_elem, "stateOrCountry", rp.address.state_or_country)
                add_text_element(ra_elem, "zipCode", rp.address.zip_code)
            if rp.relationships:
                rel_list = child_element(info, "relatedPersonRelationshipList")
                for rel in rp.relationships:
                    add_text_element(rel_list, "relationship", rel)
            add_text_element(info, "relationshipClarification", rp.clarification)

    od_elem = child_element(root, "offeringData")
    if doc.industry_group:
        ig_elem = child_element(od_elem, "industryGroup")
        add_text_element(ig_elem, "industryGroupType", doc.industry_group)
    if doc.federal_exemptions:
        fe_elem = child_element(od_elem, "federalExemptionsExclusions")
        for item in doc.federal_exemptions:
            add_text_element(fe_elem, "item", item)
    if doc.offering_amounts:
        amt_elem = child_element(od_elem, "offeringSalesAmounts")
        if doc.offering_amounts.is_indefinite:
            add_text_element(amt_elem, "totalOfferingAmount", "Indefinite")
            add_text_element(amt_elem, "totalRemaining", "Indefinite")
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
            add_text_element(amt_elem, "totalOfferingAmount", tot)
            add_text_element(amt_elem, "totalRemaining", rem)
        sold = (
            str(int(doc.offering_amounts.total_amount_sold))
            if doc.offering_amounts.total_amount_sold is not None
            else None
        )
        add_text_element(amt_elem, "totalAmountSold", sold)

    if doc.signatures:
        sb_elem = child_element(od_elem, "signatureBlock")
        for sig in doc.signatures:
            sig_elem = child_element(sb_elem, "signature")
            add_text_element(sig_elem, "issuerName", sig.issuer_name)
            add_text_element(sig_elem, "signatureName", sig.signature_name)
            add_text_element(sig_elem, "nameOfSigner", sig.name_of_signer)
            add_text_element(sig_elem, "signatureTitle", sig.signature_title)
            add_text_element(sig_elem, "signatureDate", sig.signature_date)

    return canonical_xml_output(root)


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
