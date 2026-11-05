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
    local_name,
    xml_element_text,
)


def _text(elem: ET.Element | None) -> str | None:
    return xml_element_text(elem) or None


def _find_all(parent: ET.Element, tag_name: str) -> list[ET.Element]:
    return [child for child in parent if local_name(child.tag) == tag_name]


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
        name=_text(children.get("name")) or "",
        title=_text(children.get("title")) or "",
        cusip=_text(children.get("cusip")) or "",
        lei=_text(children.get("lei")),
        isin=isin,
        balance=_text(children.get("balance")),
        units=_text(children.get("units")),
        currency_code=currency.get("curCd") if currency is not None else None,
        value_usd=_text(children.get("valUSD")),
        percent_value=_text(children.get("pctVal")),
        payoff_profile=_text(children.get("payoffProfile")),
        asset_category=_text(children.get("assetCat")),
        issuer_category=_text(children.get("issuerCat")),
        investment_country=_text(children.get("invCountry")),
        is_restricted=_text(children.get("isRestrictedSec")),
        fair_value_level=_text(children.get("fairValLevel")),
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
            _parse_investment(row) for row in _find_all(schedule, "invstOrSec")
        )
    return FormNPortDocument(
        submission_type=_text(header_children.get("submissionType")) or "",
        registrant_name=_text(gen_children.get("regName")) or "",
        investments=investments,
        filer_cik=(
            _text(find_child_element(credentials, "cik"))
            if credentials is not None
            else None
        ),
        is_confidential=_text(header_children.get("isConfidential")),
        registrant_file_number=_text(gen_children.get("regFileNumber")),
        registrant_cik=_text(gen_children.get("regCik")),
        registrant_lei=_text(gen_children.get("regLei")),
        series_name=_text(gen_children.get("seriesName")),
        series_lei=_text(gen_children.get("seriesLei")),
        report_period_end=_text(gen_children.get("repPdEnd")),
        report_period_date=_text(gen_children.get("repPdDate")),
        is_final_filing=_text(gen_children.get("isFinalFiling")),
        total_assets=_text(fund_children.get("totAssets")),
        total_liabilities=_text(fund_children.get("totLiabs")),
        net_assets=_text(fund_children.get("netAssets")),
    )


__all__ = ["parse_nport_xml"]
