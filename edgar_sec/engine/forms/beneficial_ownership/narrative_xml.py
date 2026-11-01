"""Narrative section XML serialization for Schedule 13D and 13G."""

from __future__ import annotations

from decimal import Decimal
import xml.etree.ElementTree as ET

from edgar_sec.domain.forms.families.beneficial_ownership.models import (
    BeneficialOwnershipDocument,
    EvidenceState,
    NarrativeItem,
)
from edgar_sec.domain.taxonomy.jurisdictions import EDGAR_JURISDICTION_CODES
from edgar_sec.engine.forms.common.extraction import (
    FieldKind,
    FieldSpec,
    extract_value,
)
from edgar_sec.engine.forms.common.numbers import normalize_schema_number


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
    if item.number in {2, 5} and not item.parsed_fields:
        return
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

    if item.parsed_fields:
        tag_rename_13d = {
            "securitiesClassTitle": "securityTitle",
            "principalBusiness": "principalJob",
            "citizenshipOrOrganization": "citizenship",
            "fundType": "fundsSource",
        }
        for f in item.parsed_fields:
            if item.number != 5 or f.tag not in {
                "aggregateAmountOwned",
                "percentOfClass",
            }:
                actual_tag = tag_rename_13d.get(f.tag, f.tag)
                _add_text(elem, actual_tag, f.value)
        return
    f_map = {
        1: "commentText",
        2: "filingPersonName",
        3: "fundsSource",
        4: "transactionPurpose",
        5: "percentageOfClassSecurities",
        6: "contractDescription",
        7: "filedExhibits",
    }
    text_val = item.text
    if item.number == 1 and not text_val and doc:
        text_val = f"Security: {doc.issuer.security_class or ''}; Issuer: {doc.issuer.issuer_name or ''}".strip()
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
                    _add_text(item_element, mapped_name, field.value)
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
                        _add_schema_jurisdiction(
                            item_element,
                            mapped_name,
                            field.value,
                            f"items.item{item.number}.{field.tag}",
                            unresolved,
                        )
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
                    _add_schema_jurisdiction(
                        item_element,
                        "citizenship",
                        p_cit,
                        "items.item2.citizenshipOrOrganization",
                        unresolved,
                    )
    elif item.number == 4 and item.parsed_fields:
        item_element = ET.SubElement(parent, _tag("item4"))
        shares_elem: ET.Element | None = None
        shares_map = {
            "soleVotingPower": "solePowerOrDirectToVote",
            "sharedVotingPower": "sharedPowerOrDirectToVote",
            "soleDispositivePower": "solePowerOrDirectToDispose",
            "sharedDispositivePower": "sharedPowerOrDirectToDispose",
        }
        for field in item.parsed_fields:
            if field.tag in {"aggregateAmountOwned", "percentOfClass"}:
                is_agg = field.tag == "aggregateAmountOwned"
                tname = "amountBeneficiallyOwned" if is_agg else "classPercent"
                _add_schema_number(
                    item_element,
                    tname,
                    field.value,
                    integer=is_agg,
                    max_length=16 if is_agg else 5,
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
                    integer=True,
                    max_length=16,
                    path=f"items.item4.{s_name}",
                    unresolved=unresolved,
                )
        if shares_elem is not None and len(shares_elem) == 0:
            item_element.remove(shares_elem)
        if len(item_element) == 0:
            parent.remove(item_element)
            item_element = None
    elif item.number in {3, 5, 6, 7, 8, 9, 10} and item.parsed_fields:
        item_element = ET.SubElement(parent, _tag(f"item{item.number}"))
        field_tags = {f.tag: f.value for f in item.parsed_fields}
        if item.number == 3:
            if field_tags.get("notApplicableFlag") == "Y":
                _add_text(item_element, "notApplicableFlag", "Y")
            else:
                _add_text(item_element, "notApplicableFlag", "N")
                for f in item.parsed_fields:
                    if f.tag in {"typeOfReportingPerson", "typeOfPersonFiling"}:
                        for code in f.value.split(","):
                            clean_code = code.strip()
                            if clean_code:
                                _add_text(
                                    item_element, "typeOfPersonFiling", clean_code
                                )
        elif item.number == 5:
            if field_tags.get("notApplicableFlag") == "Y":
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
            if field_tags.get("notApplicableFlag") == "Y":
                _add_text(item_element, "notApplicableFlag", "Y")
            else:
                _add_text(item_element, "notApplicableFlag", "N")
                if target_tag in field_tags:
                    _add_text(item_element, target_tag, field_tags[target_tag])
        elif item.number == 10:
            if field_tags.get("notApplicableFlag") == "Y":
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
