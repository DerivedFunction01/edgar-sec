"""Canonical XML renderer for SEC Form 25-NSE filings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from edgar_sec.domain.forms.families.form_25nse.models import Form25NseDocument
from edgar_sec.domain.forms.families.form_25nse.taxonomy import FORM25NSE_XML_SPEC
from edgar_sec.engine.document_processing.outputs import HandlerOutput
from edgar_sec.engine.forms.common.native_xml import passthrough_sec_xml
from edgar_sec.engine.forms.common.xml_builder import (
    add_text_element,
    canonical_xml_output,
    child_element,
    root_element,
)
from edgar_sec.engine.forms.form_25nse.xml_parser import parse_form_25nse_xml

if TYPE_CHECKING:
    from edgar_sec.engine.document_processing.registry import HandlerContext


def build_form_25nse_xml(doc: Form25NseDocument) -> HandlerOutput:
    """Serialize the domain model in the document schema's element order."""
    root = root_element("notificationOfRemoval")
    add_text_element(root, "schemaVersion", doc.schema_version)
    exchange = child_element(root, "exchange")
    add_text_element(exchange, "cik", doc.exchange.cik)
    add_text_element(exchange, "ccc", doc.exchange.ccc)
    add_text_element(exchange, "entityName", doc.exchange.entity_name)
    issuer = child_element(root, "issuer")
    add_text_element(issuer, "cik", doc.issuer.cik)
    add_text_element(issuer, "entityName", doc.issuer.entity_name)
    add_text_element(issuer, "fileNumber", doc.issuer.file_number)
    if doc.issuer.address is not None:
        address = child_element(issuer, "address")
        add_text_element(address, "street1", doc.issuer.address.street1)
        add_text_element(address, "street2", doc.issuer.address.street2)
        add_text_element(address, "city", doc.issuer.address.city)
        add_text_element(
            address, "stateOrCountryCode", doc.issuer.address.state_or_country_code
        )
        add_text_element(address, "zipCode", doc.issuer.address.zip_code)
    add_text_element(issuer, "telephoneNumber", doc.issuer.telephone_number)
    add_text_element(root, "descriptionClassSecurity", doc.description_class_security)
    add_text_element(root, "ruleProvision", doc.rule_provision)
    signature = child_element(root, "signatureData")
    add_text_element(signature, "signatureName", doc.signature.name)
    add_text_element(signature, "signatureTitle", doc.signature.title)
    add_text_element(signature, "signatureDate", doc.signature.date)
    return canonical_xml_output(root)


def render_form_25nse_to_xml(
    raw_bytes: bytes,
    context: HandlerContext | None = None,
) -> HandlerOutput:
    """Render 25-NSE input to canonical XML with pass-through fast path."""
    passthrough = passthrough_sec_xml(raw_bytes, FORM25NSE_XML_SPEC)
    if passthrough is not None:
        return passthrough
    doc = parse_form_25nse_xml(raw_bytes)
    if doc is None:
        raise ValueError("payload carries no notificationOfRemoval document")
    return build_form_25nse_xml(doc)


__all__ = ["build_form_25nse_xml", "render_form_25nse_to_xml"]
