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
from edgar_sec.engine.forms.common.extraction import local_name


def _text(elem: ET.Element | None) -> str | None:
    if elem is None or elem.text is None:
        return None
    val = elem.text.strip()
    return val if val else None


def _find_first(parent: ET.Element, tag_name: str) -> ET.Element | None:
    for child in parent:
        if local_name(child.tag) == tag_name:
            return child
    return None


def _find_path(parent: ET.Element, *tags: str) -> ET.Element | None:
    current: ET.Element | None = parent
    for tag in tags:
        if current is None:
            return None
        current = _find_first(current, tag)
    return current


def _notification_root(root: ET.Element) -> ET.Element | None:
    if local_name(root.tag) == "notificationOfRemoval":
        return root
    if local_name(root.tag) == "edgarSubmission":
        return _find_path(
            root, "primaryDocument", "documentBlock", "notificationOfRemoval"
        )
    return None


def _parse_address(elem: ET.Element | None) -> IssuerAddress | None:
    if elem is None:
        return None
    return IssuerAddress(
        street1=_text(_find_first(elem, "street1")),
        street2=_text(_find_first(elem, "street2")),
        city=_text(_find_first(elem, "city")),
        state_or_country_code=_text(_find_first(elem, "stateOrCountryCode")),
        zip_code=_text(_find_first(elem, "zipCode")),
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
    exchange_elem = _find_first(notification, "exchange")
    exchange = ExchangeFiler(
        cik=_text(_find_first(exchange_elem, "cik"))
        if exchange_elem is not None
        else None,
        ccc=_text(_find_first(exchange_elem, "ccc"))
        if exchange_elem is not None
        else None,
        entity_name=(
            _text(_find_first(exchange_elem, "entityName"))
            if exchange_elem is not None
            else None
        ),
    )
    issuer_elem = _find_first(notification, "issuer")
    issuer = RemovalIssuer(
        cik=_text(_find_first(issuer_elem, "cik")) if issuer_elem is not None else None,
        entity_name=(
            _text(_find_first(issuer_elem, "entityName"))
            if issuer_elem is not None
            else None
        ),
        file_number=(
            _text(_find_first(issuer_elem, "fileNumber"))
            if issuer_elem is not None
            else None
        ),
        address=(
            _parse_address(_find_first(issuer_elem, "address"))
            if issuer_elem is not None
            else None
        ),
        telephone_number=(
            _text(_find_first(issuer_elem, "telephoneNumber"))
            if issuer_elem is not None
            else None
        ),
    )
    signature_elem = _find_first(notification, "signatureData")
    signature = RemovalSignature(
        name=(
            _text(_find_first(signature_elem, "signatureName"))
            if signature_elem is not None
            else None
        ),
        title=(
            _text(_find_first(signature_elem, "signatureTitle"))
            if signature_elem is not None
            else None
        ),
        date=(
            _text(_find_first(signature_elem, "signatureDate"))
            if signature_elem is not None
            else None
        ),
    )
    return Form25NseDocument(
        schema_version=_text(_find_first(notification, "schemaVersion")),
        exchange=exchange,
        issuer=issuer,
        description_class_security=_text(
            _find_first(notification, "descriptionClassSecurity")
        ),
        rule_provision=_text(_find_first(notification, "ruleProvision")),
        signature=signature,
    )


__all__ = ["parse_form_25nse_xml"]
