"""Serializes a BeneficialOwnershipDocument into conforming SEC XML."""

from __future__ import annotations

from decimal import Decimal
import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping

from edgar_sec.domain.forms.common.checkmarks import CANONICAL_CHECKED
from edgar_sec.domain.forms.common.signatures import Signatory
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
from edgar_sec.engine.forms.beneficial_ownership.narrative_xml import (
    render_narrative_13d_xml,
    render_narrative_13g_xml,
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
from edgar_sec.domain.forms.families.beneficial_ownership.taxonomy import (
    COMMON_XML_NAMESPACE,
    SCHEDULE_13D_XML_NAMESPACE,
    SCHEDULE_13G_XML_NAMESPACE,
)
from edgar_sec.engine.forms.beneficial_ownership.vocabulary import (
    RE_GROUP_OPTION,
)
from edgar_sec.engine.forms.common.marks import resolve_checked_labeled_option
from edgar_sec.engine.forms.common.unparsed import serialize_unparsed_sections
from edgar_sec.engine.forms.common.signatures import clean_signature_name


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
    elem = ET.SubElement(parent, _tag(name))
    for f, v in (
        ("street1", address.street1),
        ("street2", address.street2),
        ("city", address.city),
        ("zipCode", address.zip_code),
    ):
        _add_text(elem, f, v, common=True)
    _add_schema_jurisdiction(
        elem,
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
    res = extract_value(
        value,
        FieldSpec(
            path,
            FieldKind.JURISDICTION,
            allowed_values=EDGAR_JURISDICTION_CODES,
        ),
    )
    if res.value is not None:
        _add_text(parent, name, res.value, common=common)
    elif rec := res.unresolved_record():
        unresolved.append(rec)


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
    clean = value.strip().lower()
    if clean in {"a", "b"}:
        return clean
    return resolve_checked_labeled_option(value, RE_GROUP_OPTION)


def _add_checkbox_value(
    parent: ET.Element,
    evidence: CoverItemEvidence | None,
    name: str,
) -> None:
    if evidence is not None and evidence.state in {
        EvidenceState.CHECKED,
        EvidenceState.UNCHECKED,
    }:
        _add_text(
            parent,
            name,
            "Y" if evidence.state is EvidenceState.CHECKED else "N",
        )


def _unresolved_record(
    doc: BeneficialOwnershipDocument,
    field_path: str,
    value: str,
    reported_year_anchor: int | None = None,
    *,
    status: str = "unresolved",
    normalized_value: str | None = None,
) -> dict[str, object]:
    ev = next((i for i in doc.field_extractions if i.field_path == field_path), None)
    return (
        build_scalar_evidence_record(
            field_path,
            ev.source_text if ev is not None else value,
            status=status,
            normalized_value=normalized_value,
            start_offset=ev.start_offset if ev is not None else None,
            end_offset=ev.end_offset if ev is not None else None,
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
        extract_leading_number=True,
        allow_integral_decimal=integer,
    )
    if normalized is not None and not integer and "." in normalized:
        trimmed = normalized.rstrip("0").rstrip(".")
        if trimmed:
            normalized = trimmed
        if len(normalized) > max_length:
            try:
                dec = Decimal(normalized)
                decimals_allowed = max(0, max_length - len(str(int(dec))) - 1)
                normalized = (
                    f"{dec:.{decimals_allowed}f}"
                    if decimals_allowed > 0
                    else str(round(dec))
                )
            except Exception:
                pass
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
    _add_text(
        info,
        "memberOfGroup",
        _checked_group(
            _source_value(person, "memberOfGroup") or _source_value(person, 2)
        ),
    )
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
    p_path = f"formData.reportingPersons.reportingPersonInfo[{person_index}]"
    for tag_name, fallback_num in REPORTING_PERSON_XML_SLOTS:
        _add_schema_number(
            info,
            tag_name,
            _first_value(person, tag_name) or _first_value(person, fallback_num),
            integer=True,
            max_length=17,
            path=f"{p_path}.{tag_name}",
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
        path=f"{p_path}.percentOfClass",
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
    _add_text(
        info,
        "memberGroup",
        _checked_group(
            _source_value(person, "memberOfGroup") or _source_value(person, 2)
        ),
    )
    p_path = f"formData.coverPageHeaderReportingPersonDetails[{person_index}]"
    _add_schema_jurisdiction(
        info,
        "citizenshipOrOrganization",
        _first_value(person, "citizenshipOrOrganization") or _first_value(person, 4),
        f"{p_path}.citizenshipOrOrganization",
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
            path=f"{p_path}.reportingPersonBeneficiallyOwnedNumberOfShares.{name}",
            doc=doc,
            unresolved=unresolved,
        )
    _add_schema_number(
        info,
        "reportingPersonBeneficiallyOwnedAggregateNumberOfShares",
        _first_value(person, "aggregateAmountOwned") or _first_value(person, 9),
        integer=True,
        max_length=17,
        path=f"{p_path}.reportingPersonBeneficiallyOwnedAggregateNumberOfShares",
        doc=doc,
        unresolved=unresolved,
    )
    _add_schema_number(
        info,
        "classPercent",
        _first_value(person, "percentOfClass") or _first_value(person, 11),
        integer=False,
        max_length=5,
        path=f"{p_path}.classPercent",
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
    reference_year: int | None = None,
) -> None:
    cover = ET.SubElement(parent, _tag("coverPageHeader"))
    _add_text(cover, "securitiesClassTitle", doc.issuer.security_class)
    event_date = doc.issuer.event_date
    if not event_date and doc.signature_block and doc.signature_block.signatories:
        event_date = next(
            (s.date for s in doc.signature_block.signatories if s.date), None
        )
    _add_schema_date(
        cover,
        (
            "eventDateRequiresFilingThisStatement"
            if doc.form_family == "13G"
            else "dateOfEvent"
        ),
        event_date,
        reference_year,
        "formData.coverPageHeader.dateOfEvent",
        doc,
        unresolved,
    )
    if any(
        (
            doc.issuer.issuer_cik,
            doc.issuer.issuer_name,
            doc.issuer.cusip,
            doc.issuer.issuer_address,
        )
    ):
        issuer = ET.SubElement(cover, _tag("issuerInfo"))
        _add_text(
            issuer,
            "issuerCik" if doc.form_family == "13G" else "issuerCIK",
            doc.issuer.issuer_cik,
        )
        if doc.issuer.cusip:
            _add_text(
                ET.SubElement(issuer, _tag("issuerCusips")),
                "issuerCusipNumber",
                doc.issuer.cusip,
            )
        _add_text(issuer, "issuerName", doc.issuer.issuer_name)
        if doc.issuer.issuer_address:
            addr_tag = (
                "issuerPrincipalExecutiveOfficeAddress"
                if doc.form_family == "13G"
                else "address"
            )
            _address_xml(issuer, addr_tag, doc.issuer.issuer_address, unresolved)
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
        elif rec := build_scalar_evidence_record(
            "ruleDesignation", doc.rule_designation, status="unresolved"
        ):
            unresolved.append(rec)

    if any(
        (
            doc.issuer.notice_contact,
            doc.issuer.notice_phone,
            doc.issuer.notice_address,
        )
    ):
        notification = ET.SubElement(
            ET.SubElement(cover, _tag("authorizedPersons")),
            _tag("notificationInfo"),
        )
        _add_text(notification, "personName", doc.issuer.notice_contact)
        _add_text(notification, "personPhoneNum", doc.issuer.notice_phone)
        if doc.issuer.notice_address:
            _address_xml(
                notification, "personAddress", doc.issuer.notice_address, unresolved
            )


def _signature_xml(
    parent: ET.Element,
    doc: BeneficialOwnershipDocument,
    reference_year: int | None,
    unresolved: list[dict[str, object]],
) -> None:
    is_13g = doc.form_family == "13G"
    signature_info = ET.SubElement(
        parent, _tag("signatureInformation" if is_13g else "signatureInfo")
    )
    if doc.signature_block is None or not doc.signature_block.signatories:
        sig_name = (
            _first_value(doc.reporting_persons[0], "reportingPersonName")
            if doc.reporting_persons
            else "Authorized Signatory"
        ) or "Authorized Signatory"
        signatories = [
            Signatory(
                name=sig_name,
                title="Authorized Signatory",
                date=doc.issuer.event_date,
            )
        ]
    else:
        signatories = list(doc.signature_block.signatories)

    def _signer_reporting_name(idx: int, p_name: str) -> str | None:
        p_clean = p_name.casefold().strip()
        matched = next(
            (
                n
                for rp in doc.reporting_persons
                if (n := _first_value(rp, "reportingPersonName"))
                and n.casefold().strip() == p_clean
            ),
            None,
        )
        rps = doc.reporting_persons
        if matched is None and len(rps) == 1:
            return _first_value(rps[0], "reportingPersonName")
        if matched is None and len(rps) == len(signatories):
            return _first_value(rps[idx - 1], "reportingPersonName")
        return matched

    block_dates = [
        p.date
        for p in signatories
        if p.date and normalize_iso_date(p.date, reference_year)
    ]
    fallback_date = next((d for d in block_dates if d), None) or doc.issuer.event_date
    if is_13g:
        for idx, person in enumerate(signatories, start=1):
            _add_text(
                signature_info,
                "reportingPersonName",
                _signer_reporting_name(idx, person.name),
            )
    for person_index, person in enumerate(signatories, start=1):
        signature_person = (
            signature_info
            if is_13g
            else ET.SubElement(signature_info, _tag("signaturePerson"))
        )
        if not is_13g:
            _add_text(
                signature_person,
                "signatureReportingPerson",
                _signer_reporting_name(person_index, person.name),
            )
        details = ET.SubElement(signature_person, _tag("signatureDetails"))
        clean_name = (
            clean_signature_name(person.name) or person.name or "Authorized Signatory"
        )
        _add_text(details, "signature", clean_name)
        _add_text(details, "title", person.title or "Authorized Signatory")
        sig_date = person.date or fallback_date
        _add_schema_date(
            details,
            "date",
            sig_date,
            reference_year,
            (
                f"formData.{('signatureInformation' if is_13g else 'signatureInfo')}"
                f".signaturePerson[{person_index}].signatureDetails.date"
            ),
            doc,
            unresolved,
        )


def _unparsed_records(
    doc: BeneficialOwnershipDocument,
    unresolved: list[dict[str, object]],
) -> list[Mapping[str, object]]:
    def _rec(role: str, text: str, start: int, end: int) -> dict[str, object]:
        return {
            "role": role,
            "content_type": "text/plain",
            "content": text,
            "start_offset": start,
            "end_offset": end,
        }

    records: list[Mapping[str, object]] = [
        _rec(s.role, s.text, s.start_offset, s.end_offset)
        for s in doc.unparsed_sections
    ]
    records.extend(
        _rec(
            f"item{it.number}.unparsed",
            it.text or it.raw_heading,
            it.start_offset,
            it.end_offset,
        )
        for it in doc.narrative_items
        if doc.form_family == "13D" and it.number in {2, 5} and not it.parsed_fields
    )
    records.extend(unresolved)
    return records


def build_beneficial_ownership_xml(
    doc: BeneficialOwnershipDocument,
    reference_year: int | None = None,
) -> HandlerOutput:
    """Builds conforming SEC XML document for Schedule 13D or 13G."""
    ns_uri = (
        SCHEDULE_13G_XML_NAMESPACE
        if doc.form_family == "13G"
        else SCHEDULE_13D_XML_NAMESPACE
    )
    root = ET.Element(
        "edgarSubmission",
        {"xmlns": ns_uri, "xmlns:com": COMMON_XML_NAMESPACE},
    )
    _add_text(root, "schemaVersion", "X0202")
    header = ET.SubElement(root, _tag("headerData"))
    _add_text(header, "submissionType", doc.submission_type)
    _add_text(header, "previousAccessionNumber", doc.previous_accession_number)
    form_data = ET.SubElement(root, _tag("formData"))
    unresolved: list[dict[str, object]] = []
    if reference_year is None:
        source_dates = [doc.issuer.event_date]
        if doc.signature_block:
            source_dates.extend(s.date for s in doc.signature_block.signatories)
        reference_year = resolve_reference_year(None, None, source_dates)
    _cover_xml(form_data, doc, unresolved, reference_year)
    if doc.reporting_persons:
        is_13g = doc.form_family == "13G"
        people = (
            form_data if is_13g else ET.SubElement(form_data, _tag("reportingPersons"))
        )
        fn = _reporting_person_13g_xml if is_13g else _reporting_person_xml
        for index, person in enumerate(doc.reporting_persons, start=1):
            fn(people, person, index, doc, unresolved)
    tag_name = "items" if doc.form_family == "13G" else "items1To7"
    items = ET.SubElement(form_data, _tag(tag_name))
    items_to_render = doc.narrative_items
    if items_to_render:
        first_by_number: dict[int, NarrativeItem] = {}
        repeated: dict[int, list[NarrativeItem]] = {}
        for item in items_to_render:
            if item.number not in first_by_number:
                first_by_number[item.number] = item
            else:
                repeated.setdefault(item.number, []).append(item)
        for number in sorted(first_by_number):
            item = first_by_number[number]
            if reps := repeated.get(number):
                all_text = [item.text] + [r.text for r in reps if r.text]
                all_fields = list(item.parsed_fields)
                for r in reps:
                    all_fields.extend(r.parsed_fields)
                item = NarrativeItem(
                    number=item.number,
                    heading=item.heading,
                    text="\n\n".join(t for t in all_text if t).strip(),
                    start_offset=item.start_offset,
                    end_offset=reps[-1].end_offset,
                    raw_heading=item.raw_heading,
                    parsed_fields=tuple(all_fields),
                )
            if doc.form_family == "13G":
                render_narrative_13g_xml(items, item, unresolved, doc=doc)
            else:
                render_narrative_13d_xml(items, item, doc=doc)
    if len(items) == 0:
        if doc.form_family == "13G":
            render_narrative_13g_xml(
                items,
                NarrativeItem(1, "Item 1", "", 0, 0),
                unresolved,
                doc=doc,
            )
            render_narrative_13g_xml(
                items,
                NarrativeItem(2, "Item 2", "", 0, 0),
                unresolved,
                doc=doc,
            )
            if len(items) == 0:
                elem1 = ET.SubElement(items, _tag("item1"))
                _add_text(elem1, "issuerName", doc.issuer.issuer_name or "Issuer")
        else:
            render_narrative_13d_xml(
                items,
                NarrativeItem(1, "Item 1", "", 0, 0),
                doc=doc,
            )
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
    "build_beneficial_ownership_xml",
    "build_schedule13d_xml",
]
