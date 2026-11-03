"""Parser for SEC Form N-PORT XML documents."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from edgar_sec.domain.forms.families.form_nport.models import (
    FormNPortDocument,
    NPortInvestment,
)
from edgar_sec.engine.forms.common.extraction import (
    find_child_element,
    local_name,
    xml_element_text,
)


def _text(elem: ET.Element | None) -> str | None:
    return xml_element_text(elem) or None


def _find_all(parent: ET.Element, tag_name: str) -> list[ET.Element]:
    return [child for child in parent if local_name(child.tag) == tag_name]


def _parse_investment(row_elem: ET.Element) -> NPortInvestment:
    identifiers = find_child_element(row_elem, "identifiers")
    isin = None
    if identifiers is not None:
        isin_elem = find_child_element(identifiers, "isin")
        if isin_elem is not None:
            isin = isin_elem.get("value")
    currency = find_child_element(row_elem, "currencyConditional")
    return NPortInvestment(
        name=_text(find_child_element(row_elem, "name")) or "",
        title=_text(find_child_element(row_elem, "title")) or "",
        cusip=_text(find_child_element(row_elem, "cusip")) or "",
        lei=_text(find_child_element(row_elem, "lei")),
        isin=isin,
        balance=_text(find_child_element(row_elem, "balance")),
        units=_text(find_child_element(row_elem, "units")),
        currency_code=currency.get("curCd") if currency is not None else None,
        value_usd=_text(find_child_element(row_elem, "valUSD")),
        percent_value=_text(find_child_element(row_elem, "pctVal")),
        payoff_profile=_text(find_child_element(row_elem, "payoffProfile")),
        asset_category=_text(find_child_element(row_elem, "assetCat")),
        issuer_category=_text(find_child_element(row_elem, "issuerCat")),
        investment_country=_text(find_child_element(row_elem, "invCountry")),
        is_restricted=_text(find_child_element(row_elem, "isRestrictedSec")),
        fair_value_level=_text(find_child_element(row_elem, "fairValLevel")),
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
    form_data = find_child_element(root, "formData")
    gen_info = (
        find_child_element(form_data, "genInfo") if form_data is not None else None
    )
    fund_info = (
        find_child_element(form_data, "fundInfo") if form_data is not None else None
    )
    schedule = (
        find_child_element(form_data, "invstOrSecs") if form_data is not None else None
    )
    investments: tuple[NPortInvestment, ...] = ()
    if schedule is not None:
        investments = tuple(
            _parse_investment(row) for row in _find_all(schedule, "invstOrSec")
        )
    return FormNPortDocument(
        submission_type=(
            _text(find_child_element(header, "submissionType")) or ""
            if header is not None
            else ""
        ),
        registrant_name=(
            _text(find_child_element(gen_info, "regName")) or ""
            if gen_info is not None
            else ""
        ),
        investments=investments,
        filer_cik=(
            _text(find_child_element(credentials, "cik"))
            if credentials is not None
            else None
        ),
        is_confidential=(
            _text(find_child_element(header, "isConfidential"))
            if header is not None
            else None
        ),
        registrant_file_number=(
            _text(find_child_element(gen_info, "regFileNumber"))
            if gen_info is not None
            else None
        ),
        registrant_cik=(
            _text(find_child_element(gen_info, "regCik"))
            if gen_info is not None
            else None
        ),
        registrant_lei=(
            _text(find_child_element(gen_info, "regLei"))
            if gen_info is not None
            else None
        ),
        series_name=(
            _text(find_child_element(gen_info, "seriesName"))
            if gen_info is not None
            else None
        ),
        series_lei=(
            _text(find_child_element(gen_info, "seriesLei"))
            if gen_info is not None
            else None
        ),
        report_period_end=(
            _text(find_child_element(gen_info, "repPdEnd"))
            if gen_info is not None
            else None
        ),
        report_period_date=(
            _text(find_child_element(gen_info, "repPdDate"))
            if gen_info is not None
            else None
        ),
        is_final_filing=(
            _text(find_child_element(gen_info, "isFinalFiling"))
            if gen_info is not None
            else None
        ),
        total_assets=(
            _text(find_child_element(fund_info, "totAssets"))
            if fund_info is not None
            else None
        ),
        total_liabilities=(
            _text(find_child_element(fund_info, "totLiabs"))
            if fund_info is not None
            else None
        ),
        net_assets=(
            _text(find_child_element(fund_info, "netAssets"))
            if fund_info is not None
            else None
        ),
    )


__all__ = ["parse_nport_xml"]
