"""Parser for SEC Form 25-NSE XML documents."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from edgar_sec.domain.forms.families.form_25nse.models import (
    ExchangeFiler,
    Form25NseDocument,
    IssuerAddress,
    RemovalIssuer,
    RemovalSignature,
)
from edgar_sec.engine.forms.common.extraction import (
    find_child_element,
    find_element_path,
    local_name,
    xml_element_text_or_none,
)


def _notification_root(root: ET.Element) -> ET.Element | None:
    if local_name(root.tag) == "notificationOfRemoval":
        return root
    if local_name(root.tag) == "edgarSubmission":
        return find_element_path(
            root, "primaryDocument", "documentBlock", "notificationOfRemoval"
        )
    return None


def _parse_address(elem: ET.Element | None) -> IssuerAddress | None:
    if elem is None:
        return None
    return IssuerAddress(
        street1=xml_element_text_or_none(find_child_element(elem, "street1")),
        street2=xml_element_text_or_none(find_child_element(elem, "street2")),
        city=xml_element_text_or_none(find_child_element(elem, "city")),
        state_or_country_code=xml_element_text_or_none(
            find_child_element(elem, "stateOrCountryCode")
        ),
        zip_code=xml_element_text_or_none(find_child_element(elem, "zipCode")),
    )


def parse_form_25nse_xml(raw_bytes: bytes) -> Form25NseDocument | None:
    """Parse a 25-NSE primary into the domain model; None when absent."""
    try:
        root = ET.fromstring(raw_bytes)
    except ET.ParseError:
        return None
    notification = _notification_root(root)
    if notification is None:
        return None
    exchange_elem = find_child_element(notification, "exchange")
    exchange = ExchangeFiler(
        cik=xml_element_text_or_none(find_child_element(exchange_elem, "cik"))
        if exchange_elem is not None
        else None,
        ccc=xml_element_text_or_none(find_child_element(exchange_elem, "ccc"))
        if exchange_elem is not None
        else None,
        entity_name=(
            xml_element_text_or_none(find_child_element(exchange_elem, "entityName"))
            if exchange_elem is not None
            else None
        ),
    )
    issuer_elem = find_child_element(notification, "issuer")
    issuer = RemovalIssuer(
        cik=xml_element_text_or_none(find_child_element(issuer_elem, "cik"))
        if issuer_elem is not None
        else None,
        entity_name=(
            xml_element_text_or_none(find_child_element(issuer_elem, "entityName"))
            if issuer_elem is not None
            else None
        ),
        file_number=(
            xml_element_text_or_none(find_child_element(issuer_elem, "fileNumber"))
            if issuer_elem is not None
            else None
        ),
        address=(
            _parse_address(find_child_element(issuer_elem, "address"))
            if issuer_elem is not None
            else None
        ),
        telephone_number=(
            xml_element_text_or_none(find_child_element(issuer_elem, "telephoneNumber"))
            if issuer_elem is not None
            else None
        ),
    )
    signature_elem = find_child_element(notification, "signatureData")
    signature = RemovalSignature(
        name=(
            xml_element_text_or_none(
                find_child_element(signature_elem, "signatureName")
            )
            if signature_elem is not None
            else None
        ),
        title=(
            xml_element_text_or_none(
                find_child_element(signature_elem, "signatureTitle")
            )
            if signature_elem is not None
            else None
        ),
        date=(
            xml_element_text_or_none(
                find_child_element(signature_elem, "signatureDate")
            )
            if signature_elem is not None
            else None
        ),
    )
    return Form25NseDocument(
        schema_version=xml_element_text_or_none(
            find_child_element(notification, "schemaVersion")
        ),
        exchange=exchange,
        issuer=issuer,
        description_class_security=xml_element_text_or_none(
            find_child_element(notification, "descriptionClassSecurity")
        ),
        rule_provision=xml_element_text_or_none(
            find_child_element(notification, "ruleProvision")
        ),
        signature=signature,
    )


__all__ = ["parse_form_25nse_xml"]
