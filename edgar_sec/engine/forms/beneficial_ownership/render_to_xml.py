"""Serializes a BeneficialOwnershipDocument into conforming SEC XML."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping

from edgar_sec.domain.forms.common.checkmarks import CANONICAL_CHECKED
from edgar_sec.domain.forms.families.beneficial_ownership.models import (
    AddressDetails,
    BeneficialOwnershipDocument,
    CoverItemEvidence,
    EvidenceState,
    NarrativeItem,
    ReportingPersonCover,
)
from edgar_sec.domain.taxonomy.jurisdictions import EDGAR_JURISDICTION_CODES
from edgar_sec.engine.forms.common.extraction import (
    FieldKind,
    FieldSpec,
    build_scalar_evidence_record,
    extract_value,
)
from edgar_sec.domain.forms.families.beneficial_ownership.taxonomy import (
    SCHEDULE_13G_RULE_TYPES,
)
from edgar_sec.engine.forms.beneficial_ownership.cover_value_diagnostics import (
    two_character_codes,
)
from edgar_sec.engine.forms.beneficial_ownership.vocabulary import (
    REPORTING_PERSON_XML_SLOTS,
)
from edgar_sec.engine.document_processing.outputs import HandlerOutput, HandlerSidecar
from edgar_sec.engine.forms.common.numbers import (
    normalize_schema_number,
)
from edgar_sec.engine.forms.common.dates import (
    format_iso_date,
    normalize_iso_date,
    reported_year,
    resolve_reference_year,
)
from edgar_sec.engine.forms.common.unparsed import serialize_unparsed_sections

SCHEDULE_13D_NS = "http://www.sec.gov/edgar/schedule13D"
SCHEDULE_13G_NS = "http://www.sec.gov/edgar/schedule13G"
COMMON_NS = "http://www.sec.gov/edgar/common"
_RE_GROUP_OPTION = re.compile(r"(?i)(?:\(\s*([ab])\s*\)|(?<!\w)([ab])[.)])")


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


def _address_xml(
    parent: ET.Element,
    name: str,
    address: AddressDetails,
    unresolved: list[dict[str, object]],
) -> None:
    element = ET.SubElement(parent, _tag(name))
    for field, value in (
        ("street1", address.street1),
        ("street2", address.street2),
        ("city", address.city),
        ("zipCode", address.zip_code),
    ):
        _add_text(element, field, value, common=True)
    _add_schema_jurisdiction(
        element,
        "stateOrCountry",
        address.state_or_country,
        f"{name}.stateOrCountry",
        unresolved,
        common=True,
    )


def _add_schema_jurisdiction(
    parent: ET.Element,
    name: str,
    value: str | None,
    path: str,
    unresolved: list[dict[str, object]],
    *,
    common: bool = False,
) -> None:
    result = extract_value(
        value,
        FieldSpec(
            path,
            FieldKind.JURISDICTION,
            allowed_values=EDGAR_JURISDICTION_CODES,
        ),
    )
    if result.value is not None:
        _add_text(parent, name, result.value, common=common)
    elif record := result.unresolved_record():
        unresolved.append(record)


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
            return (option.group(1) or option.group(2)).lower()
    return None


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


def _unresolved_record(
    doc: BeneficialOwnershipDocument,
    field_path: str,
    value: str,
    reported_year_anchor: int | None = None,
    *,
    status: str = "unresolved",
    normalized_value: str | None = None,
) -> dict[str, object]:
    evidence = next(
        (item for item in doc.field_extractions if item.field_path == field_path),
        None,
    )
    return (
        build_scalar_evidence_record(
            field_path,
            evidence.source_text if evidence is not None else value,
            status=status,
            normalized_value=normalized_value,
            start_offset=evidence.start_offset if evidence is not None else None,
            end_offset=evidence.end_offset if evidence is not None else None,
            reference_year=reported_year_anchor,
        )
        or {}
    )


def _add_schema_date(
    parent: ET.Element,
    name: str,
    value: str | None,
    reference_year: int | None,
    path: str,
    doc: BeneficialOwnershipDocument,
    unresolved: list[dict[str, object]],
) -> None:
    canonical = normalize_iso_date(value, reference_year)
    normalized = format_iso_date(canonical, month_first=True)
    if normalized is not None:
        _add_text(parent, name, normalized)
        evidence = _unresolved_record(
            doc,
            path,
            value,
            reference_year or reported_year((value,)),
            status="normalized",
            normalized_value=normalized,
        )
        unresolved.append(evidence)
    elif value and value.strip():
        unresolved.append(
            _unresolved_record(
                doc,
                path,
                value,
                reported_year_anchor=reference_year,
                status="invalid_date",
            )
        )


def _add_schema_number(
    parent: ET.Element,
    name: str,
    value: str | None,
    *,
    integer: bool,
    max_length: int,
    path: str,
    doc: BeneficialOwnershipDocument,
    unresolved: list[dict[str, object]],
) -> None:
    normalized = normalize_schema_number(
        value,
        integer=integer,
        strip_units=integer,
        strip_percent=not integer,
        strip_footnotes=True,
    )
    if normalized is not None and len(normalized) <= max_length:
        _add_text(parent, name, normalized)
    elif value and value.strip():
        unresolved.append(_unresolved_record(doc, path, value, status="invalid_number"))


def _reporting_person_xml(
    parent: ET.Element,
    person: ReportingPersonCover,
    person_index: int,
    doc: BeneficialOwnershipDocument,
    unresolved: list[dict[str, object]],
) -> None:
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
    for fund_type in two_character_codes(
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
    for tag_name, fallback_num in REPORTING_PERSON_XML_SLOTS:
        _add_schema_number(
            info,
            tag_name,
            _first_value(person, tag_name) or _first_value(person, fallback_num),
            integer=True,
            max_length=17,
            path=(
                "formData.reportingPersons.reportingPersonInfo"
                f"[{person_index}].{tag_name}"
            ),
            doc=doc,
            unresolved=unresolved,
        )
    _add_checkbox_value(
        info,
        person.first_item("isAggregateExcludeShares") or person.first_item(12),
        "isAggregateExcludeShares",
    )
    _add_schema_number(
        info,
        "percentOfClass",
        _first_value(person, "percentOfClass") or _first_value(person, 13),
        integer=False,
        max_length=5,
        path=(
            "formData.reportingPersons.reportingPersonInfo"
            f"[{person_index}].percentOfClass"
        ),
        doc=doc,
        unresolved=unresolved,
    )
    for type_code in two_character_codes(
        _first_value(person, "typeOfReportingPerson") or _first_value(person, 14)
    ):
        _add_text(info, "typeOfReportingPerson", type_code)
    _add_text(info, "commentContent", person.comment_content)


def _reporting_person_13g_xml(
    parent: ET.Element,
    person: ReportingPersonCover,
    person_index: int,
    doc: BeneficialOwnershipDocument,
    unresolved: list[dict[str, object]],
) -> None:
    info = ET.SubElement(parent, _tag("coverPageHeaderReportingPersonDetails"))
    _add_text(info, "reportingPersonName", _first_value(person, "reportingPersonName"))
    _add_text(info, "memberGroup", _first_value(person, "memberOfGroup"))
    _add_schema_jurisdiction(
        info,
        "citizenshipOrOrganization",
        _first_value(person, "citizenshipOrOrganization") or _first_value(person, 4),
        f"formData.coverPageHeaderReportingPersonDetails[{person_index}].citizenshipOrOrganization",
        unresolved,
    )
    shares = ET.SubElement(info, _tag("reportingPersonBeneficiallyOwnedNumberOfShares"))
    for name, number in (
        ("soleVotingPower", 5),
        ("sharedVotingPower", 6),
        ("soleDispositivePower", 7),
        ("sharedDispositivePower", 8),
    ):
        _add_schema_number(
            shares,
            name,
            _first_value(person, name) or _first_value(person, number),
            integer=True,
            max_length=17,
            path=(
                "formData.coverPageHeaderReportingPersonDetails"
                f"[{person_index}].reportingPersonBeneficiallyOwnedNumberOfShares.{name}"
            ),
            doc=doc,
            unresolved=unresolved,
        )
    _add_schema_number(
        info,
        "reportingPersonBeneficiallyOwnedAggregateNumberOfShares",
        _first_value(person, "aggregateAmountOwned") or _first_value(person, 9),
        integer=True,
        max_length=17,
        path=(
            "formData.coverPageHeaderReportingPersonDetails"
            f"[{person_index}].reportingPersonBeneficiallyOwnedAggregateNumberOfShares"
        ),
        doc=doc,
        unresolved=unresolved,
    )
    _add_schema_number(
        info,
        "classPercent",
        _first_value(person, "percentOfClass") or _first_value(person, 11),
        integer=False,
        max_length=5,
        path=f"formData.coverPageHeaderReportingPersonDetails[{person_index}].classPercent",
        doc=doc,
        unresolved=unresolved,
    )
    for type_code in two_character_codes(
        _first_value(person, "typeOfReportingPerson") or _first_value(person, 12)
    ):
        _add_text(info, "typeOfReportingPerson", type_code)
    _add_text(info, "comments", person.comment_content)


def _cover_xml(
    parent: ET.Element,
    doc: BeneficialOwnershipDocument,
    unresolved: list[dict[str, object]],
) -> None:
    cover = ET.SubElement(parent, _tag("coverPageHeader"))
    _add_text(cover, "securitiesClassTitle", doc.issuer.security_class)
    _add_schema_date(
        cover,
        (
            "eventDateRequiresFilingThisStatement"
            if doc.form_family == "13G"
            else "dateOfEvent"
        ),
        doc.issuer.event_date,
        None,
        "formData.coverPageHeader.dateOfEvent",
        doc,
        unresolved,
    )
    issuer_fields = (
        doc.issuer.issuer_cik,
        doc.issuer.issuer_name,
        doc.issuer.cusip,
        doc.issuer.issuer_address,
    )
    if any(issuer_fields):
        issuer = ET.SubElement(cover, _tag("issuerInfo"))
        _add_text(
            issuer,
            "issuerCik" if doc.form_family == "13G" else "issuerCIK",
            doc.issuer.issuer_cik,
        )
        if doc.issuer.cusip:
            cusips = ET.SubElement(issuer, _tag("issuerCusips"))
            _add_text(cusips, "issuerCusipNumber", doc.issuer.cusip)
        _add_text(issuer, "issuerName", doc.issuer.issuer_name)
        if doc.issuer.issuer_address:
            _address_xml(
                issuer,
                (
                    "issuerPrincipalExecutiveOfficeAddress"
                    if doc.form_family == "13G"
                    else "address"
                ),
                doc.issuer.issuer_address,
                unresolved,
            )
    if doc.form_family == "13G" and doc.rule_designation:
        if doc.rule_designation in SCHEDULE_13G_RULE_TYPES:
            rules = ET.SubElement(
                cover, _tag("designateRulesPursuantThisScheduleFiled")
            )
            _add_text(
                rules,
                "designateRulePursuantThisScheduleFiled",
                doc.rule_designation,
            )
        else:
            unresolved.append(
                build_scalar_evidence_record(
                    "ruleDesignation",
                    doc.rule_designation,
                    status="unresolved",
                )
                or {}
            )

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
            _address_xml(
                notification, "personAddress", doc.issuer.notice_address, unresolved
            )


def _narrative_xml(parent: ET.Element, item: NarrativeItem) -> None:
    if item.number in {2, 5} and not item.parsed_fields:
        return
    item_name = "item1" if item.number == 1 else f"Item{item.number}"
    item_element = ET.SubElement(parent, _tag(item_name))
    if item.parsed_fields:
        for field in item.parsed_fields:
            _add_text(item_element, field.tag, field.value)
        return
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


def _narrative_xml_13g(
    parent: ET.Element,
    item: NarrativeItem,
    unresolved: list[dict[str, object]],
) -> bool:
    field_names = {
        "filingPersonName": "filingPersonName",
        "principalBusinessAddress": "principalBusinessOfficeOrResidenceAddress",
        "citizenshipOrOrganization": "citizenship",
    }
    item_element: ET.Element | None = None
    if item.number == 2 and item.parsed_fields:
        for field in item.parsed_fields:
            if mapped_name := field_names.get(field.tag):
                if item_element is None:
                    item_element = ET.SubElement(parent, _tag("Item2"))
                if mapped_name == "citizenship":
                    _add_schema_jurisdiction(
                        item_element,
                        mapped_name,
                        field.value,
                        f"items1To7.item{item.number}.{field.tag}",
                        unresolved,
                    )
                else:
                    _add_text(item_element, mapped_name, field.value)
    if item_element is None or item.text:
        unresolved.append(
            {
                "role": f"item{item.number}.unparsed",
                "content_type": "text/plain",
                "content": item.text or item.raw_heading,
                "start_offset": item.start_offset,
                "end_offset": item.end_offset,
            }
        )
    return item_element is not None


def _signature_xml(
    parent: ET.Element,
    doc: BeneficialOwnershipDocument,
    reference_year: int | None,
    unresolved: list[dict[str, object]],
) -> None:
    if doc.signature_block is None or not doc.signature_block.signatories:
        return
    is_13g = doc.form_family == "13G"
    signature_info = ET.SubElement(
        parent, _tag("signatureInformation" if is_13g else "signatureInfo")
    )
    if is_13g:
        for person in doc.signature_block.signatories:
            reporting_name = next(
                (
                    name
                    for reporting_person in doc.reporting_persons
                    if (name := _first_value(reporting_person, "reportingPersonName"))
                    and name.casefold().strip() == person.name.casefold().strip()
                ),
                None,
            )
            _add_text(signature_info, "reportingPersonName", reporting_name)
    for person_index, person in enumerate(doc.signature_block.signatories, start=1):
        signature_person = (
            signature_info
            if is_13g
            else ET.SubElement(signature_info, _tag("signaturePerson"))
        )
        if not is_13g:
            reporting_name = next(
                (
                    name
                    for reporting_person in doc.reporting_persons
                    if (name := _first_value(reporting_person, "reportingPersonName"))
                    and name.casefold().strip() == person.name.casefold().strip()
                ),
                None,
            )
            _add_text(signature_person, "signatureReportingPerson", reporting_name)
        details = ET.SubElement(signature_person, _tag("signatureDetails"))
        _add_text(details, "signature", person.name)
        _add_text(details, "title", person.title)
        _add_schema_date(
            details,
            "date",
            person.date,
            reference_year,
            (
                f"formData.{('signatureInformation' if is_13g else 'signatureInfo')}"
                f".signaturePerson"
                f"[{person_index}].signatureDetails.date"
            ),
            doc,
            unresolved,
        )


def _unparsed_records(
    doc: BeneficialOwnershipDocument,
    unresolved: list[dict[str, object]],
) -> list[Mapping[str, object]]:
    records: list[Mapping[str, object]] = [
        {
            "role": section.role,
            "content_type": "text/plain",
            "content": section.text,
            "start_offset": section.start_offset,
            "end_offset": section.end_offset,
        }
        for section in doc.unparsed_sections
    ]
    records.extend(
        {
            "role": f"item{item.number}.unparsed",
            "content_type": "text/plain",
            "content": item.text or item.raw_heading,
            "start_offset": item.start_offset,
            "end_offset": item.end_offset,
        }
        for item in doc.narrative_items
        if doc.form_family == "13D" and item.number in {2, 5} and not item.parsed_fields
    )
    records.extend(unresolved)
    return records


def build_beneficial_ownership_xml(
    doc: BeneficialOwnershipDocument,
    reference_year: int | None = None,
) -> HandlerOutput:
    """Builds conforming SEC XML document for Schedule 13D or 13G."""
    ns_uri = SCHEDULE_13G_NS if doc.form_family == "13G" else SCHEDULE_13D_NS
    root = ET.Element(
        "edgarSubmission",
        {"xmlns": ns_uri, "xmlns:com": COMMON_NS},
    )
    _add_text(root, "schemaVersion", "X0202")
    header = ET.SubElement(root, _tag("headerData"))
    _add_text(header, "submissionType", doc.submission_type)
    _add_text(header, "previousAccessionNumber", doc.previous_accession_number)
    form_data = ET.SubElement(root, _tag("formData"))
    unresolved: list[dict[str, object]] = []
    if reference_year is None:
        reference_year = resolve_reference_year(None, None, (doc.issuer.event_date,))
    _cover_xml(form_data, doc, unresolved)
    if doc.reporting_persons:
        if doc.form_family == "13G":
            for index, person in enumerate(doc.reporting_persons, start=1):
                _reporting_person_13g_xml(form_data, person, index, doc, unresolved)
        else:
            people = ET.SubElement(form_data, _tag("reportingPersons"))
            for index, person in enumerate(doc.reporting_persons, start=1):
                _reporting_person_xml(people, person, index, doc, unresolved)
    items_to_render = doc.narrative_items
    if items_to_render:
        tag_name = "items" if doc.form_family == "13G" else "items1To7"
        items = ET.SubElement(form_data, _tag(tag_name))
        first_by_number: dict[int, NarrativeItem] = {}
        repeated: dict[int, list[str]] = {}
        for item in items_to_render:
            if item.number in first_by_number:
                repeated.setdefault(item.number, []).append(item.text)
            else:
                first_by_number[item.number] = item
        emitted_item = False
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
            if doc.form_family == "13G":
                emitted_item = (
                    _narrative_xml_13g(items, item, unresolved) or emitted_item
                )
            else:
                _narrative_xml(items, item)
        if doc.form_family == "13G" and not emitted_item:
            form_data.remove(items)
    _signature_xml(form_data, doc, reference_year, unresolved)
    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    sidecar = serialize_unparsed_sections(_unparsed_records(doc, unresolved))
    return HandlerOutput(
        content=xml_bytes,
        sidecars=(HandlerSidecar("unparsed_sections.json", sidecar),),
    )


def build_schedule13d_xml(doc: BeneficialOwnershipDocument) -> HandlerOutput:
    return build_beneficial_ownership_xml(doc)


__all__ = [
    "COMMON_NS",
    "SCHEDULE_13D_NS",
    "SCHEDULE_13G_NS",
    "build_beneficial_ownership_xml",
    "build_schedule13d_xml",
]
