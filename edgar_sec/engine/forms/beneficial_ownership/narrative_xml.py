"""Narrative section XML serialization for Schedule 13D and 13G."""

from __future__ import annotations

from decimal import Decimal
import xml.etree.ElementTree as ET

from edgar_sec.domain.forms.families.beneficial_ownership.models import (
    BeneficialOwnershipDocument,
    EvidenceState,
    NarrativeItem,
    ReportingPersonCover,
)
from edgar_sec.domain.forms.families.beneficial_ownership.taxonomy import (
    SCHEDULE_13G_BUSINESS_ENGAGED_TYPES,
)
from edgar_sec.domain.taxonomy.jurisdictions import (
    EDGAR_JURISDICTION_CODES,
    edgar_jurisdiction_code_in_text,
)
from edgar_sec.engine.forms.common.extraction import (
    FieldKind,
    FieldSpec,
    extract_value,
)
from edgar_sec.engine.forms.common.numbers import normalize_schema_number
from edgar_sec.engine.forms.common.tables import strip_separator_runs


def _first_value(person: ReportingPersonCover, key: str | int) -> str | None:
    item = person.first_item(key)
    return item.value if item and item.state is EvidenceState.VALUE else None


def _tag(name: str) -> str:
    return name


def _add_text(parent: ET.Element, name: str, value: str | None) -> ET.Element | None:
    if value is None or not value.strip():
        return None
    element = ET.SubElement(parent, _tag(name))
    element.text = value
    return element


def _add_schema_jurisdiction(
    parent: ET.Element,
    name: str,
    value: str | None,
    path: str,
    unresolved: list[dict[str, object]],
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
        _add_text(parent, name, res.value)
    else:
        code = edgar_jurisdiction_code_in_text(value) if value else None
        if code:
            _add_text(parent, name, code)
        elif rec := res.unresolved_record():
            unresolved.append(rec)


def _add_schema_number(
    parent: ET.Element,
    name: str,
    value: str | None,
    *,
    integer: bool,
    max_length: int,
    path: str,
    unresolved: list[dict[str, object]],
) -> None:
    is_percent = name in {"classPercent", "percentOfClass"}
    normalized = normalize_schema_number(
        value,
        integer=integer,
        strip_units=not is_percent,
        strip_percent=is_percent,
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
        raw_value = value.strip()
        if len(raw_value) <= 20000:
            _add_text(parent, name, raw_value)
        else:
            unresolved.append(
                {
                    "role": f"normalization.unresolved:{path}",
                    "content_type": "text/plain",
                    "content": value,
                    "status": "invalid_number",
                }
            )


def render_narrative_13d_xml(
    parent: ET.Element,
    item: NarrativeItem,
    doc: BeneficialOwnershipDocument | None = None,
) -> None:
    """Render Schedule 13D narrative item XML conforming to X0202."""
    elem = ET.SubElement(parent, _tag(f"item{item.number}"))
    if item.number == 1:
        parsed_dict = (
            {f.tag: f.value for f in item.parsed_fields} if item.parsed_fields else {}
        )
        sec_title = (
            parsed_dict.get("securityTitle")
            or parsed_dict.get("securitiesClassTitle")
            or (doc.issuer.security_class if doc else None)
        )
        _add_text(elem, "securityTitle", sec_title)
        iss_name = parsed_dict.get("issuerName") or (
            doc.issuer.issuer_name if doc else None
        )
        if iss_name:
            iss_name = strip_separator_runs(iss_name)
        _add_text(elem, "issuerName", iss_name)
        if doc and doc.issuer.issuer_address:
            addr_elem = ET.SubElement(elem, _tag("issuerPrincipalAddress"))
            for f_name, val in (
                ("street1", doc.issuer.issuer_address.street1),
                ("street2", doc.issuer.issuer_address.street2),
                ("city", doc.issuer.issuer_address.city),
                ("stateOrCountry", doc.issuer.issuer_address.state_or_country),
                ("zipCode", doc.issuer.issuer_address.zip_code),
            ):
                if val and val.strip():
                    _add_text(addr_elem, f_name, val.strip())
        elif parsed_addr := parsed_dict.get("issuerPrincipalAddress"):
            addr_elem = ET.SubElement(elem, _tag("issuerPrincipalAddress"))
            _add_text(addr_elem, "street1", parsed_addr.strip())
        comment_val = parsed_dict.get("commentText") or item.text
        if comment_val and comment_val.strip():
            _add_text(elem, "commentText", comment_val.strip())
        return

    tag_rename_13d = {
        "securitiesClassTitle": "securityTitle",
        "principalBusiness": "principalJob",
        "citizenshipOrOrganization": "citizenship",
        "fundType": "fundsSource",
    }
    if item.parsed_fields:
        for f in item.parsed_fields:
            if item.number != 5 or f.tag not in {
                "aggregateAmountOwned",
                "percentOfClass",
            }:
                actual_tag = tag_rename_13d.get(f.tag, f.tag)
                _add_text(elem, actual_tag, f.value)
        if item.number != 5 and len(elem) > 0:
            return

    if item.number == 2:
        if doc and doc.reporting_persons:
            rp = doc.reporting_persons[0]
            _add_text(
                elem,
                "filingPersonName",
                _first_value(rp, "reportingPersonName") or _first_value(rp, 1),
            )
            _add_text(
                elem,
                "citizenship",
                _first_value(rp, "citizenshipOrOrganization") or _first_value(rp, 6),
            )
        elif item.text and len(item.text.strip()) <= 240:
            _add_text(elem, "filingPersonName", item.text.strip())
        return

    if item.number == 5:
        if elem.find("percentageOfClassSecurities") is None:
            pct = None
            if doc and doc.reporting_persons:
                rp = doc.reporting_persons[0]
                pct = _first_value(rp, "percentOfClass") or _first_value(rp, 13)
            if not pct and item.text and len(item.text.strip()) <= 240:
                pct = item.text.strip()
            _add_text(elem, "percentageOfClassSecurities", pct or "0.0")
        if elem.find("numberOfShares") is None and doc and doc.reporting_persons:
            rp = doc.reporting_persons[0]
            shs = _first_value(rp, "aggregateAmountOwned") or _first_value(rp, 9)
            if shs:
                _add_text(elem, "numberOfShares", shs)
        if item.text and elem.find("transactionDesc") is None:
            _add_text(elem, "transactionDesc", item.text.strip()[:20000])
        return

    f_map = {
        3: "fundsSource",
        4: "transactionPurpose",
        6: "contractDescription",
        7: "filedExhibits",
    }
    text_val = item.text
    if not text_val and doc and doc.reporting_persons and item.number == 3:
        text_val = _first_value(doc.reporting_persons[0], "fundType") or _first_value(
            doc.reporting_persons[0], 4
        )
    if not text_val:
        text_val = "Not applicable" if item.number == 4 else "None"
    _add_text(elem, f_map.get(item.number, "commentText"), text_val)


def render_narrative_13g_xml(
    parent: ET.Element,
    item: NarrativeItem,
    unresolved: list[dict[str, object]],
    doc: BeneficialOwnershipDocument | None = None,
) -> bool:
    """Render Schedule 13G narrative item XML conforming to X0202."""
    field_names_2 = {
        "filingPersonName": "filingPersonName",
        "principalBusinessAddress": "principalBusinessOfficeOrResidenceAddress",
        "principalBusinessOfficeOrResidenceAddress": "principalBusinessOfficeOrResidenceAddress",
        "citizenshipOrOrganization": "citizenship",
        "citizenship": "citizenship",
    }
    field_names_1 = {
        "issuerName": "issuerName",
        "issuerAddress": "issuerPrincipalExecutiveOfficeAddress",
        "issuerPrincipalAddress": "issuerPrincipalExecutiveOfficeAddress",
        "issuerPrincipalExecutiveOfficeAddress": "issuerPrincipalExecutiveOfficeAddress",
    }
    item_element: ET.Element | None = None
    if item.number == 1:
        if item.parsed_fields:
            for field in item.parsed_fields:
                if mapped_name := field_names_1.get(field.tag):
                    if item_element is None:
                        item_element = ET.SubElement(parent, _tag("item1"))
                    val = (
                        strip_separator_runs(field.value)
                        if mapped_name == "issuerName"
                        else field.value
                    )
                    _add_text(item_element, mapped_name, val)
        elif doc and (doc.issuer.issuer_name or doc.issuer.issuer_address):
            item_element = ET.SubElement(parent, _tag("item1"))
            _add_text(item_element, "issuerName", doc.issuer.issuer_name)
            if doc.issuer.issuer_address:
                _add_text(
                    item_element,
                    "issuerPrincipalExecutiveOfficeAddress",
                    doc.issuer.issuer_address.raw_text,
                )
    elif item.number == 2:
        if item.parsed_fields:
            for field in item.parsed_fields:
                if mapped_name := field_names_2.get(field.tag):
                    if item_element is None:
                        item_element = ET.SubElement(parent, _tag("item2"))
                    if mapped_name == "citizenship":
                        _add_text(item_element, mapped_name, field.value)
                    else:
                        _add_text(item_element, mapped_name, field.value)
        elif doc and doc.reporting_persons:
            first_person = doc.reporting_persons[0]
            name_ev = first_person.first_item(
                "reportingPersonName"
            ) or first_person.first_item(1)
            p_name = (
                name_ev.value
                if name_ev and name_ev.state is EvidenceState.VALUE
                else None
            )
            cit_ev = first_person.first_item(
                "citizenshipOrOrganization"
            ) or first_person.first_item(4)
            p_cit = (
                cit_ev.value if cit_ev and cit_ev.state is EvidenceState.VALUE else None
            )
            if p_name or p_cit:
                item_element = ET.SubElement(parent, _tag("item2"))
                _add_text(item_element, "filingPersonName", p_name)
                if p_cit:
                    _add_text(item_element, "citizenship", p_cit)
    elif item.number == 3:
        item_element = ET.SubElement(parent, _tag("item3"))
        if item.parsed_fields:
            field_tags = {f.tag: f.value for f in item.parsed_fields}
            codes = tuple(
                dict.fromkeys(
                    clean_code
                    for field in item.parsed_fields
                    if field.tag in {"typeOfReportingPerson", "typeOfPersonFiling"}
                    for code in field.value.split(",")
                    if (clean_code := code.strip())
                    and clean_code in SCHEDULE_13G_BUSINESS_ENGAGED_TYPES
                )
            )
            not_applicable = field_tags.get("notApplicableFlag") == "Y" or not codes
            _add_text(item_element, "notApplicableFlag", "Y" if not_applicable else "N")
            for code in codes:
                _add_text(item_element, "typeOfPersonFiling", code)
        elif doc and doc.reporting_persons:
            rp = doc.reporting_persons[0]
            codes = _first_value(rp, "typeOfReportingPerson") or _first_value(rp, 12)
            valid_codes = tuple(
                dict.fromkeys(
                    code.strip()
                    for code in (codes or "").split(",")
                    if code.strip() in SCHEDULE_13G_BUSINESS_ENGAGED_TYPES
                )
            )
            _add_text(item_element, "notApplicableFlag", "N" if valid_codes else "Y")
            for code in valid_codes:
                _add_text(item_element, "typeOfPersonFiling", code)
        else:
            _add_text(item_element, "notApplicableFlag", "Y")
    elif item.number == 4:
        item_element = ET.SubElement(parent, _tag("item4"))
        shares_elem: ET.Element | None = None
        shares_map = {
            "soleVotingPower": "solePowerOrDirectToVote",
            "sharedVotingPower": "sharedPowerOrDirectToVote",
            "soleDispositivePower": "solePowerOrDirectToDispose",
            "sharedDispositivePower": "sharedPowerOrDirectToDispose",
        }
        if item.parsed_fields:
            for field in item.parsed_fields:
                if field.tag in {"aggregateAmountOwned", "percentOfClass"}:
                    tname = (
                        "amountBeneficiallyOwned"
                        if field.tag == "aggregateAmountOwned"
                        else "classPercent"
                    )
                    _add_schema_number(
                        item_element,
                        tname,
                        field.value,
                        integer=False,
                        max_length=16 if field.tag == "aggregateAmountOwned" else 5,
                        path=f"items.item4.{tname}",
                        unresolved=unresolved,
                    )
                elif field.tag in shares_map:
                    if shares_elem is None:
                        shares_elem = ET.SubElement(
                            item_element, _tag("numberOfSharesPersonHas")
                        )
                    s_name = shares_map[field.tag]
                    _add_schema_number(
                        shares_elem,
                        s_name,
                        field.value,
                        integer=False,
                        max_length=16,
                        path=f"items.item4.{s_name}",
                        unresolved=unresolved,
                    )
        elif doc and doc.reporting_persons:
            rp = doc.reporting_persons[0]
            amt = _first_value(rp, "aggregateAmountOwned") or _first_value(rp, 9)
            pct = _first_value(rp, "percentOfClass") or _first_value(rp, 11)
            if amt:
                _add_schema_number(
                    item_element,
                    "amountBeneficiallyOwned",
                    amt,
                    integer=False,
                    max_length=16,
                    path="items.item4.amountBeneficiallyOwned",
                    unresolved=unresolved,
                )
            if pct:
                _add_schema_number(
                    item_element,
                    "classPercent",
                    pct,
                    integer=False,
                    max_length=5,
                    path="items.item4.classPercent",
                    unresolved=unresolved,
                )
            for f_name, fallback_num in (
                ("soleVotingPower", 5),
                ("sharedVotingPower", 6),
                ("soleDispositivePower", 7),
                ("sharedDispositivePower", 8),
            ):
                val = _first_value(rp, f_name) or _first_value(rp, fallback_num)
                if val:
                    if shares_elem is None:
                        shares_elem = ET.SubElement(
                            item_element, _tag("numberOfSharesPersonHas")
                        )
                    s_name = shares_map[f_name]
                    _add_schema_number(
                        shares_elem,
                        s_name,
                        val,
                        integer=False,
                        max_length=16,
                        path=f"items.item4.{s_name}",
                        unresolved=unresolved,
                    )
        if shares_elem is not None and len(shares_elem) == 0:
            item_element.remove(shares_elem)
        if len(item_element) == 0:
            parent.remove(item_element)
            item_element = None
    elif item.number in {5, 6, 7, 8, 9, 10}:
        item_element = ET.SubElement(parent, _tag(f"item{item.number}"))
        field_tags = (
            {f.tag: f.value for f in item.parsed_fields} if item.parsed_fields else {}
        )
        if item.number == 5:
            if field_tags.get("notApplicableFlag") == "Y" or not field_tags:
                _add_text(item_element, "notApplicableFlag", "Y")
            else:
                _add_text(item_element, "notApplicableFlag", "N")
                if field_tags.get("is5PercentCessation") == "Y":
                    _add_text(item_element, "classOwnership5PercentOrLess", "Y")
        elif item.number in {6, 7, 8, 9}:
            tag_map = {
                6: "ownershipMoreThan5PercentOnBehalfOfAnotherPerson",
                7: "subsidiaryIdentificationAndClassification",
                8: "identificationAndClassificationOfGroupMembers",
                9: "groupDissolutionNotice",
            }
            target_tag = tag_map[item.number]
            if field_tags.get("notApplicableFlag") == "Y" or not field_tags:
                _add_text(item_element, "notApplicableFlag", "Y")
            else:
                _add_text(item_element, "notApplicableFlag", "N")
                if target_tag in field_tags:
                    _add_text(item_element, target_tag, field_tags[target_tag])
        elif item.number == 10:
            if field_tags.get("notApplicableFlag") == "Y" or not field_tags:
                _add_text(item_element, "notApplicableFlag", "Y")
            else:
                _add_text(item_element, "notApplicableFlag", "N")
                if "certifications" in field_tags:
                    _add_text(
                        item_element, "certifications", field_tags["certifications"]
                    )

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
