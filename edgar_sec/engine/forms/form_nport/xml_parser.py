"""Parser for SEC Form N-PORT XML documents."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from edgar_sec.domain.forms.families.form_nport.models import (
    FormNPortDocument,
    NPortInvestment,
)
from edgar_sec.engine.forms.common.extraction import (
    child_element_index,
    find_child_element,
    find_child_elements,
    xml_element_text_or_none,
)


def _parse_investment(row_elem: ET.Element) -> NPortInvestment:
    children = child_element_index(row_elem)
    identifiers = children.get("identifiers")
    isin = None
    if identifiers is not None:
        isin_elem = child_element_index(identifiers).get("isin")
        if isin_elem is not None:
            isin = isin_elem.get("value")
    currency = children.get("currencyConditional")
    return NPortInvestment(
        name=xml_element_text_or_none(children.get("name")) or "",
        title=xml_element_text_or_none(children.get("title")) or "",
        cusip=xml_element_text_or_none(children.get("cusip")) or "",
        lei=xml_element_text_or_none(children.get("lei")),
        isin=isin,
        balance=xml_element_text_or_none(children.get("balance")),
        units=xml_element_text_or_none(children.get("units")),
        currency_code=currency.get("curCd") if currency is not None else None,
        value_usd=xml_element_text_or_none(children.get("valUSD")),
        percent_value=xml_element_text_or_none(children.get("pctVal")),
        payoff_profile=xml_element_text_or_none(children.get("payoffProfile")),
        asset_category=xml_element_text_or_none(children.get("assetCat")),
        issuer_category=xml_element_text_or_none(children.get("issuerCat")),
        investment_country=xml_element_text_or_none(children.get("invCountry")),
        is_restricted=xml_element_text_or_none(children.get("isRestrictedSec")),
        fair_value_level=xml_element_text_or_none(children.get("fairValLevel")),
    )


def parse_nport_xml(raw_bytes: bytes) -> FormNPortDocument:
    """Parse raw Form N-PORT XML bytes into the typed domain model."""
    root = ET.fromstring(raw_bytes)
    header = find_child_element(root, "headerData")
    filer_info = find_child_element(header, "filerInfo") if header is not None else None
    filer = find_child_element(filer_info, "filer") if filer_info is not None else None
    credentials = (
        find_child_element(filer, "issuerCredentials") if filer is not None else None
    )
    header_children = child_element_index(header)
    form_data = find_child_element(root, "formData")
    form_children = child_element_index(form_data)
    gen_children = child_element_index(form_children.get("genInfo"))
    fund_children = child_element_index(form_children.get("fundInfo"))
    schedule = form_children.get("invstOrSecs")
    investments: tuple[NPortInvestment, ...] = ()
    if schedule is not None:
        investments = tuple(
            _parse_investment(row)
            for row in find_child_elements(schedule, "invstOrSec")
        )
    return FormNPortDocument(
        submission_type=xml_element_text_or_none(header_children.get("submissionType"))
        or "",
        registrant_name=xml_element_text_or_none(gen_children.get("regName")) or "",
        investments=investments,
        filer_cik=(
            xml_element_text_or_none(find_child_element(credentials, "cik"))
            if credentials is not None
            else None
        ),
        is_confidential=xml_element_text_or_none(header_children.get("isConfidential")),
        registrant_file_number=xml_element_text_or_none(
            gen_children.get("regFileNumber")
        ),
        registrant_cik=xml_element_text_or_none(gen_children.get("regCik")),
        registrant_lei=xml_element_text_or_none(gen_children.get("regLei")),
        series_name=xml_element_text_or_none(gen_children.get("seriesName")),
        series_lei=xml_element_text_or_none(gen_children.get("seriesLei")),
        report_period_end=xml_element_text_or_none(gen_children.get("repPdEnd")),
        report_period_date=xml_element_text_or_none(gen_children.get("repPdDate")),
        is_final_filing=xml_element_text_or_none(gen_children.get("isFinalFiling")),
        total_assets=xml_element_text_or_none(fund_children.get("totAssets")),
        total_liabilities=xml_element_text_or_none(fund_children.get("totLiabs")),
        net_assets=xml_element_text_or_none(fund_children.get("netAssets")),
    )


__all__ = ["parse_nport_xml"]
