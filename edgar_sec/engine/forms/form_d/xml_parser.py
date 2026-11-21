"""Streaming parser for SEC Form D XML submissions."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from edgar_sec.domain.forms.families.form_d.models import (
    FormDDocument,
    IssuerAddress,
    OfferingSalesAmounts,
    PrimaryIssuer,
    RelatedPerson,
    Signatory,
)
from edgar_sec.engine.forms.common.extraction import (
    find_child_element,
    find_child_elements,
    xml_element_text_or_none,
)


def _float(elem: ET.Element | None) -> float | None:
    txt = xml_element_text_or_none(elem)
    if not txt:
        return None
    try:
        return float(txt.replace(",", "").replace("$", ""))
    except ValueError:
        return None


def _parse_address(addr_elem: ET.Element | None) -> IssuerAddress | None:
    if addr_elem is None:
        return None
    s1 = xml_element_text_or_none(find_child_element(addr_elem, "street1")) or ""
    s2 = xml_element_text_or_none(find_child_element(addr_elem, "street2"))
    city = xml_element_text_or_none(find_child_element(addr_elem, "city")) or ""
    sc = xml_element_text_or_none(find_child_element(addr_elem, "stateOrCountry")) or ""
    sc_desc = xml_element_text_or_none(
        find_child_element(addr_elem, "stateOrCountryDescription")
    )
    zip_code = xml_element_text_or_none(find_child_element(addr_elem, "zipCode"))
    return IssuerAddress(s1, s2, city, sc, sc_desc, zip_code)


def _parse_primary_issuer(pi_elem: ET.Element | None) -> PrimaryIssuer:
    if pi_elem is None:
        return PrimaryIssuer("", "", None, None, None, None, None)
    cik = xml_element_text_or_none(find_child_element(pi_elem, "cik")) or ""
    entity_name = (
        xml_element_text_or_none(find_child_element(pi_elem, "entityName")) or ""
    )
    addr = _parse_address(find_child_element(pi_elem, "issuerAddress"))
    phone = xml_element_text_or_none(find_child_element(pi_elem, "issuerPhoneNumber"))
    jur = xml_element_text_or_none(find_child_element(pi_elem, "jurisdictionOfInc"))
    etype = xml_element_text_or_none(find_child_element(pi_elem, "entityType"))
    year_elem = find_child_element(pi_elem, "yearOfInc")
    year_str = None
    if year_elem is not None:
        over5 = find_child_element(year_elem, "overFiveYears")
        if (
            over5 is not None
            and (xml_element_text_or_none(over5) or "").lower() == "true"
        ):
            year_str = "Over Five Years"
        else:
            w5 = find_child_element(year_elem, "withinFiveYears")
            year_str = (
                xml_element_text_or_none(find_child_element(w5, "value"))
                if w5 is not None
                else None
            )
    return PrimaryIssuer(cik, entity_name, addr, phone, jur, etype, year_str)


def _parse_related_persons(
    rp_list_elem: ET.Element | None,
) -> tuple[RelatedPerson, ...]:
    if rp_list_elem is None:
        return ()
    persons: list[RelatedPerson] = []
    for info in find_child_elements(rp_list_elem, "relatedPersonInfo"):
        name_elem = find_child_element(info, "relatedPersonName")
        fn = (
            xml_element_text_or_none(find_child_element(name_elem, "firstName"))
            if name_elem is not None
            else None
        )
        mn = (
            xml_element_text_or_none(find_child_element(name_elem, "middleName"))
            if name_elem is not None
            else None
        )
        ln = (
            xml_element_text_or_none(find_child_element(name_elem, "lastName"))
            if name_elem is not None
            else None
        )
        addr = _parse_address(find_child_element(info, "relatedPersonAddress"))
        r_list = find_child_element(info, "relatedPersonRelationshipList")
        rels = tuple(
            xml_element_text_or_none(r)
            for r in (
                find_child_elements(r_list, "relationship")
                if r_list is not None
                else ()
            )
            if xml_element_text_or_none(r)
        )
        clar = xml_element_text_or_none(
            find_child_element(info, "relationshipClarification")
        )
        persons.append(RelatedPerson(fn, mn, ln, addr, rels, clar))
    return tuple(persons)


def _parse_offering_amounts(od_elem: ET.Element | None) -> OfferingSalesAmounts | None:
    if od_elem is None:
        return None
    amt_elem = find_child_element(od_elem, "offeringSalesAmounts")
    if amt_elem is None:
        return None
    tot_elem = find_child_element(amt_elem, "totalOfferingAmount")
    sold_elem = find_child_element(amt_elem, "totalAmountSold")
    rem_elem = find_child_element(amt_elem, "totalRemaining")
    tot_txt = xml_element_text_or_none(tot_elem)
    is_indefinite = bool(
        (tot_txt and tot_txt.lower() == "indefinite")
        or find_child_element(amt_elem, "isIndefinite") is not None
    )
    tot = None if is_indefinite else _float(tot_elem)
    sold = _float(sold_elem)
    rem = None if is_indefinite else _float(rem_elem)
    return OfferingSalesAmounts(tot, sold, rem, is_indefinite)


def _parse_signatures(od_elem: ET.Element | None) -> tuple[Signatory, ...]:
    if od_elem is None:
        return ()
    sb_elem = find_child_element(od_elem, "signatureBlock")
    if sb_elem is None:
        return ()
    sigs: list[Signatory] = []
    for sig in find_child_elements(sb_elem, "signature"):
        issuer = xml_element_text_or_none(find_child_element(sig, "issuerName")) or ""
        sign_name = (
            xml_element_text_or_none(find_child_element(sig, "signatureName")) or ""
        )
        name = xml_element_text_or_none(find_child_element(sig, "nameOfSigner")) or ""
        title = (
            xml_element_text_or_none(find_child_element(sig, "signatureTitle")) or ""
        )
        date = xml_element_text_or_none(find_child_element(sig, "signatureDate")) or ""
        sigs.append(Signatory(issuer, sign_name, name, title, date))
    return tuple(sigs)


def parse_form_d_xml(raw_bytes: bytes) -> FormDDocument:
    """Parse raw Form D XML bytes into typed FormDDocument domain model."""
    root = ET.fromstring(raw_bytes)
    sv = xml_element_text_or_none(find_child_element(root, "schemaVersion")) or "X0101"
    st = xml_element_text_or_none(find_child_element(root, "submissionType")) or "D"
    tl = xml_element_text_or_none(find_child_element(root, "testOrLive")) or "LIVE"
    pi = _parse_primary_issuer(find_child_element(root, "primaryIssuer"))
    rp = _parse_related_persons(find_child_element(root, "relatedPersonsList"))
    od = find_child_element(root, "offeringData")
    amounts = _parse_offering_amounts(od)
    sigs = _parse_signatures(od)
    ind_grp = None
    exemptions: tuple[str, ...] = ()
    if od is not None:
        ig_elem = find_child_element(od, "industryGroup")
        if ig_elem is not None:
            ind_grp = xml_element_text_or_none(
                find_child_element(ig_elem, "industryGroupType")
            )
        fe_elem = find_child_element(od, "federalExemptionsExclusions")
        if fe_elem is not None:
            exemptions = tuple(
                xml_element_text_or_none(it)
                for it in find_child_elements(fe_elem, "item")
                if xml_element_text_or_none(it)
            )
    return FormDDocument(sv, st, tl, pi, rp, amounts, sigs, ind_grp, exemptions)


__all__ = ["parse_form_d_xml"]
