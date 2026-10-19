"""Serializes a BeneficialOwnershipDocument into conforming SEC XML."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from edgar_sec.domain.forms.common.checkmarks import CANONICAL_CHECKED
from edgar_sec.domain.forms.families.beneficial_ownership.models import (
    AddressDetails,
    BeneficialOwnershipDocument,
    CoverItemEvidence,
    EvidenceState,
    NarrativeItem,
    ReportingPersonCover,
)

SCHEDULE_13D_NS = "http://www.sec.gov/edgar/schedule13D"
SCHEDULE_13G_NS = "http://www.sec.gov/edgar/schedule13G"
COMMON_NS = "http://www.sec.gov/edgar/common"
_RE_GROUP_OPTION = re.compile(r"\(\s*([ab])\s*\)", re.IGNORECASE)
_RE_FUND_SPLIT = re.compile(r"[^A-Za-z]+")


def _tag(name: str) -> str:
    return name


def _common_tag(name: str) -> str:
    return f"com:{name}"


def _add_text(
    parent: ET.Element, name: str, value: str | None, *, common: bool = False
) -> ET.Element | None:
    if value is None or not value.strip():
        return None
    element = ET.SubElement(parent, _common_tag(name) if common else _tag(name))
    element.text = value
    return element


def _address_xml(parent: ET.Element, name: str, address: AddressDetails) -> None:
    element = ET.SubElement(parent, _tag(name))
    for field, value in (
        ("street1", address.street1),
        ("street2", address.street2),
        ("city", address.city),
        ("stateOrCountry", address.state_or_country),
        ("zipCode", address.zip_code),
    ):
        _add_text(element, field, value, common=True)


def _first_value(person: ReportingPersonCover, target: int | str) -> str | None:
    evidence = person.first_item(target)
    if evidence is None or evidence.state is not EvidenceState.VALUE:
        return None
    return evidence.value


def _source_value(person: ReportingPersonCover, target: int | str) -> str | None:
    evidence = person.first_item(target)
    return evidence.value if evidence is not None else None


def _checked_group(value: str | None) -> str | None:
    if not value:
        return None
    options = list(_RE_GROUP_OPTION.finditer(value))
    for index, option in enumerate(options):
        end = options[index + 1].start() if index + 1 < len(options) else len(value)
        if CANONICAL_CHECKED in value[option.end() : end]:
            return option.group(1).lower()
    return None


def _fund_types(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    result: list[str] = []
    for token in _RE_FUND_SPLIT.split(value):
        if len(token) == 2 and token.isupper() and token not in result:
            result.append(token)
    return tuple(result)


def _add_checkbox_value(
    parent: ET.Element,
    evidence: CoverItemEvidence | None,
    name: str,
) -> None:
    if evidence is None:
        return
    if evidence.state is EvidenceState.CHECKED:
        _add_text(parent, name, "Y")
    elif evidence.state is EvidenceState.UNCHECKED:
        _add_text(parent, name, "N")


def _reporting_person_xml(parent: ET.Element, person: ReportingPersonCover) -> None:
    info = ET.SubElement(parent, _tag("reportingPersonInfo"))
    _add_text(
        info,
        "reportingPersonName",
        _first_value(person, "reportingPersonName") or _first_value(person, 1),
    )
    member_group = _checked_group(
        _source_value(person, "memberOfGroup") or _source_value(person, 2)
    )
    _add_text(info, "memberOfGroup", member_group)
    for fund_type in _fund_types(
        _first_value(person, "fundType") or _first_value(person, 4)
    ):
        _add_text(info, "fundType", fund_type)
    _add_checkbox_value(
        info,
        person.first_item("legalProceedings") or person.first_item(5),
        "legalProceedings",
    )
    _add_text(
        info,
        "citizenshipOrOrganization",
        _first_value(person, "citizenshipOrOrganization") or _first_value(person, 6),
    )
    for tag_name, fallback_num in (
        ("soleVotingPower", 7),
        ("sharedVotingPower", 8),
        ("soleDispositivePower", 9),
        ("sharedDispositivePower", 10),
        ("aggregateAmountOwned", 11),
    ):
        _add_text(
            info,
            tag_name,
            _first_value(person, tag_name) or _first_value(person, fallback_num),
        )
    _add_checkbox_value(
        info,
        person.first_item("isAggregateExcludeShares") or person.first_item(12),
        "isAggregateExcludeShares",
    )
    _add_text(
        info,
        "percentOfClass",
        _first_value(person, "percentOfClass") or _first_value(person, 13),
    )
    for type_code in _fund_types(
        _first_value(person, "typeOfReportingPerson") or _first_value(person, 14)
    ):
        _add_text(info, "typeOfReportingPerson", type_code)
    _add_text(info, "commentContent", person.comment_content)


def _cover_xml(parent: ET.Element, doc: BeneficialOwnershipDocument) -> None:
    cover = ET.SubElement(parent, _tag("coverPageHeader"))
    _add_text(cover, "securitiesClassTitle", doc.issuer.security_class)
    _add_text(cover, "dateOfEvent", doc.issuer.event_date)
    issuer_fields = (
        doc.issuer.issuer_cik,
        doc.issuer.issuer_name,
        doc.issuer.cusip,
        doc.issuer.issuer_address,
    )
    if any(issuer_fields):
        issuer = ET.SubElement(cover, _tag("issuerInfo"))
        _add_text(issuer, "issuerCIK", doc.issuer.issuer_cik)
        if doc.issuer.cusip:
            cusips = ET.SubElement(issuer, _tag("issuerCusips"))
            _add_text(cusips, "issuerCusipNumber", doc.issuer.cusip)
        _add_text(issuer, "issuerName", doc.issuer.issuer_name)
        if doc.issuer.issuer_address:
            _address_xml(issuer, "address", doc.issuer.issuer_address)

    contact_fields = (
        doc.issuer.notice_contact,
        doc.issuer.notice_phone,
        doc.issuer.notice_address,
    )
    if any(contact_fields):
        authorized = ET.SubElement(cover, _tag("authorizedPersons"))
        notification = ET.SubElement(authorized, _tag("notificationInfo"))
        _add_text(notification, "personName", doc.issuer.notice_contact)
        _add_text(notification, "personPhoneNum", doc.issuer.notice_phone)
        if doc.issuer.notice_address:
            _address_xml(notification, "personAddress", doc.issuer.notice_address)


def _narrative_xml(parent: ET.Element, item: NarrativeItem) -> None:
    item_element = ET.SubElement(parent, _tag(f"item{item.number}"))
    field_map_13d = {
        1: "commentText",
        2: "filingPersonName",
        3: "fundsSource",
        4: "transactionPurpose",
        5: "percentageOfClassSecurities",
        6: "contractDescription",
        7: "filedExhibits",
    }
    field_name = field_map_13d.get(item.number, "commentText")
    _add_text(item_element, field_name, item.text)


def _signature_xml(parent: ET.Element, doc: BeneficialOwnershipDocument) -> None:
    if doc.signature_block is None or not doc.signature_block.signatories:
        return
    signature_info = ET.SubElement(parent, _tag("signatureInfo"))
    for person in doc.signature_block.signatories:
        signature_person = ET.SubElement(signature_info, _tag("signaturePerson"))
        details = ET.SubElement(signature_person, _tag("signatureDetails"))
        _add_text(details, "signature", person.name)
        _add_text(details, "title", person.title)
        _add_text(details, "date", person.date)


def build_beneficial_ownership_xml(doc: BeneficialOwnershipDocument) -> bytes:
    """Builds conforming SEC XML document for Schedule 13D or 13G."""
    ns_uri = SCHEDULE_13G_NS if doc.form_family == "13G" else SCHEDULE_13D_NS
    root = ET.Element(
        "edgarSubmission",
        {"xmlns": ns_uri, "xmlns:com": COMMON_NS},
    )
    _add_text(root, "schemaVersion", "X0202")
    _add_text(root, "previousAccessionNumber", doc.previous_accession_number)
    header = ET.SubElement(root, _tag("headerData"))
    _add_text(header, "submissionType", doc.submission_type)
    form_data = ET.SubElement(root, _tag("formData"))
    _cover_xml(form_data, doc)
    if doc.reporting_persons:
        people = ET.SubElement(form_data, _tag("reportingPersons"))
        for person in doc.reporting_persons:
            _reporting_person_xml(people, person)
    items_to_render = doc.narrative_items
    if items_to_render:
        tag_name = "items1To10" if doc.form_family == "13G" else "items1To7"
        items = ET.SubElement(form_data, _tag(tag_name))
        first_by_number: dict[int, NarrativeItem] = {}
        repeated: dict[int, list[str]] = {}
        for item in items_to_render:
            if item.number in first_by_number:
                repeated.setdefault(item.number, []).append(item.text)
            else:
                first_by_number[item.number] = item
        for number in sorted(first_by_number):
            item = first_by_number[number]
            additional = repeated.get(number, [])
            if additional:
                item = NarrativeItem(
                    number=item.number,
                    heading=item.heading,
                    text="\n\n".join((item.text, *additional)).strip(),
                    start_offset=item.start_offset,
                    end_offset=item.end_offset,
                )
            _narrative_xml(items, item)
    _signature_xml(form_data, doc)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def build_schedule13d_xml(doc: BeneficialOwnershipDocument) -> bytes:
    return build_beneficial_ownership_xml(doc)


__all__ = [
    "COMMON_NS",
    "SCHEDULE_13D_NS",
    "SCHEDULE_13G_NS",
    "build_beneficial_ownership_xml",
    "build_schedule13d_xml",
]
