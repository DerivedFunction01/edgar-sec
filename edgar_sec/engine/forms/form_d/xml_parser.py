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
from edgar_sec.engine.forms.common.extraction import local_name


def _text(elem: ET.Element | None) -> str | None:
    if elem is None or elem.text is None:
        return None
    val = elem.text.strip()
    return val if val else None


def _float(elem: ET.Element | None) -> float | None:
    txt = _text(elem)
    if not txt:
        return None
    try:
        return float(txt.replace(",", "").replace("$", ""))
    except ValueError:
        return None


def _find_first(parent: ET.Element, tag_name: str) -> ET.Element | None:
    for child in parent:
        if local_name(child.tag) == tag_name:
            return child
    return None


def _find_all(parent: ET.Element, tag_name: str) -> list[ET.Element]:
    return [child for child in parent if local_name(child.tag) == tag_name]


def _parse_address(addr_elem: ET.Element | None) -> IssuerAddress | None:
    if addr_elem is None:
        return None
    s1 = _text(_find_first(addr_elem, "street1")) or ""
    s2 = _text(_find_first(addr_elem, "street2"))
    city = _text(_find_first(addr_elem, "city")) or ""
    sc = _text(_find_first(addr_elem, "stateOrCountry")) or ""
    sc_desc = _text(_find_first(addr_elem, "stateOrCountryDescription"))
    zip_code = _text(_find_first(addr_elem, "zipCode"))
    return IssuerAddress(s1, s2, city, sc, sc_desc, zip_code)


def _parse_primary_issuer(pi_elem: ET.Element | None) -> PrimaryIssuer:
    if pi_elem is None:
        return PrimaryIssuer("", "", None, None, None, None, None)
    cik = _text(_find_first(pi_elem, "cik")) or ""
    entity_name = _text(_find_first(pi_elem, "entityName")) or ""
    addr = _parse_address(_find_first(pi_elem, "issuerAddress"))
    phone = _text(_find_first(pi_elem, "issuerPhoneNumber"))
    jur = _text(_find_first(pi_elem, "jurisdictionOfInc"))
    etype = _text(_find_first(pi_elem, "entityType"))
    year_elem = _find_first(pi_elem, "yearOfInc")
    year_str = None
    if year_elem is not None:
        over5 = _find_first(year_elem, "overFiveYears")
        if over5 is not None and (_text(over5) or "").lower() == "true":
            year_str = "Over Five Years"
        else:
            w5 = _find_first(year_elem, "withinFiveYears")
            year_str = _text(_find_first(w5, "value")) if w5 is not None else None
    return PrimaryIssuer(cik, entity_name, addr, phone, jur, etype, year_str)


def _parse_related_persons(
    rp_list_elem: ET.Element | None,
) -> tuple[RelatedPerson, ...]:
    if rp_list_elem is None:
        return ()
    persons: list[RelatedPerson] = []
    for info in _find_all(rp_list_elem, "relatedPersonInfo"):
        name_elem = _find_first(info, "relatedPersonName")
        fn = (
            _text(_find_first(name_elem, "firstName"))
            if name_elem is not None
            else None
        )
        mn = (
            _text(_find_first(name_elem, "middleName"))
            if name_elem is not None
            else None
        )
        ln = (
            _text(_find_first(name_elem, "lastName")) if name_elem is not None else None
        )
        addr = _parse_address(_find_first(info, "relatedPersonAddress"))
        r_list = _find_first(info, "relatedPersonRelationshipList")
        rels = tuple(
            _text(r)
            for r in (_find_all(r_list, "relationship") if r_list is not None else ())
            if _text(r)
        )
        clar = _text(_find_first(info, "relationshipClarification"))
        persons.append(RelatedPerson(fn, mn, ln, addr, rels, clar))
    return tuple(persons)


def _parse_offering_amounts(od_elem: ET.Element | None) -> OfferingSalesAmounts | None:
    if od_elem is None:
        return None
    amt_elem = _find_first(od_elem, "offeringSalesAmounts")
    if amt_elem is None:
        return None
    tot_elem = _find_first(amt_elem, "totalOfferingAmount")
    sold_elem = _find_first(amt_elem, "totalAmountSold")
    rem_elem = _find_first(amt_elem, "totalRemaining")
    tot_txt = _text(tot_elem)
    is_indefinite = bool(
        (tot_txt and tot_txt.lower() == "indefinite")
        or _find_first(amt_elem, "isIndefinite") is not None
    )
    tot = None if is_indefinite else _float(tot_elem)
    sold = _float(sold_elem)
    rem = None if is_indefinite else _float(rem_elem)
    return OfferingSalesAmounts(tot, sold, rem, is_indefinite)


def _parse_signatures(od_elem: ET.Element | None) -> tuple[Signatory, ...]:
    if od_elem is None:
        return ()
    sb_elem = _find_first(od_elem, "signatureBlock")
    if sb_elem is None:
        return ()
    sigs: list[Signatory] = []
    for sig in _find_all(sb_elem, "signature"):
        issuer = _text(_find_first(sig, "issuerName")) or ""
        sign_name = _text(_find_first(sig, "signatureName")) or ""
        name = _text(_find_first(sig, "nameOfSigner")) or ""
        title = _text(_find_first(sig, "signatureTitle")) or ""
        date = _text(_find_first(sig, "signatureDate")) or ""
        sigs.append(Signatory(issuer, sign_name, name, title, date))
    return tuple(sigs)


def parse_form_d_xml(raw_bytes: bytes) -> FormDDocument:
    """Parse raw Form D XML bytes into typed FormDDocument domain model."""
    root = ET.fromstring(raw_bytes)
    sv = _text(_find_first(root, "schemaVersion")) or "X0101"
    st = _text(_find_first(root, "submissionType")) or "D"
    tl = _text(_find_first(root, "testOrLive")) or "LIVE"
    pi = _parse_primary_issuer(_find_first(root, "primaryIssuer"))
    rp = _parse_related_persons(_find_first(root, "relatedPersonsList"))
    od = _find_first(root, "offeringData")
    amounts = _parse_offering_amounts(od)
    sigs = _parse_signatures(od)
    ind_grp = None
    exemptions: tuple[str, ...] = ()
    if od is not None:
        ig_elem = _find_first(od, "industryGroup")
        if ig_elem is not None:
            ind_grp = _text(_find_first(ig_elem, "industryGroupType"))
        fe_elem = _find_first(od, "federalExemptionsExclusions")
        if fe_elem is not None:
            exemptions = tuple(
                _text(it) for it in _find_all(fe_elem, "item") if _text(it)
            )
    return FormDDocument(sv, st, tl, pi, rp, amounts, sigs, ind_grp, exemptions)


__all__ = ["parse_form_d_xml"]
