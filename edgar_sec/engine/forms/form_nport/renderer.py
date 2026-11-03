"""Canonical XML renderer for SEC Form N-PORT filings."""

from __future__ import annotations

from typing import TYPE_CHECKING
import xml.etree.ElementTree as ET

from edgar_sec.domain.forms.families.form_nport.models import (
    FormNPortDocument,
    NPortInvestment,
)
from edgar_sec.domain.forms.families.form_nport.taxonomy import (
    NPORT_NAMESPACE,
    NPORT_XML_SPEC,
)
from edgar_sec.engine.document_processing.outputs import HandlerOutput
from edgar_sec.engine.forms.common.native_xml import passthrough_sec_xml
from edgar_sec.engine.forms.common.xml_builder import (
    add_text_element,
    canonical_xml_output,
    child_element,
    root_element,
)
from edgar_sec.engine.forms.form_nport.xml_parser import parse_nport_xml

if TYPE_CHECKING:
    from edgar_sec.engine.document_processing.registry import HandlerContext

_COMMON_NS = "http://www.sec.gov/edgar/common"


def _q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def _add_investment(parent: ET.Element, row: NPortInvestment) -> None:
    ns = NPORT_NAMESPACE
    entry = child_element(parent, _q(ns, "invstOrSec"))
    add_text_element(entry, _q(ns, "name"), row.name)
    if row.lei is not None:
        add_text_element(entry, _q(ns, "lei"), row.lei)
    add_text_element(entry, _q(ns, "title"), row.title)
    add_text_element(entry, _q(ns, "cusip"), row.cusip)
    if row.isin is not None:
        identifiers = child_element(entry, _q(ns, "identifiers"))
        isin = child_element(identifiers, _q(ns, "isin"))
        isin.set("value", row.isin)
    if row.balance is not None:
        add_text_element(entry, _q(ns, "balance"), row.balance)
    if row.units is not None:
        add_text_element(entry, _q(ns, "units"), row.units)
    if row.currency_code is not None:
        currency = child_element(entry, _q(ns, "currencyConditional"))
        currency.set("curCd", row.currency_code)
    if row.value_usd is not None:
        add_text_element(entry, _q(ns, "valUSD"), row.value_usd)
    if row.percent_value is not None:
        add_text_element(entry, _q(ns, "pctVal"), row.percent_value)
    if row.payoff_profile is not None:
        add_text_element(entry, _q(ns, "payoffProfile"), row.payoff_profile)
    if row.asset_category is not None:
        add_text_element(entry, _q(ns, "assetCat"), row.asset_category)
    if row.issuer_category is not None:
        add_text_element(entry, _q(ns, "issuerCat"), row.issuer_category)
    if row.investment_country is not None:
        add_text_element(entry, _q(ns, "invCountry"), row.investment_country)
    if row.is_restricted is not None:
        add_text_element(entry, _q(ns, "isRestrictedSec"), row.is_restricted)
    if row.fair_value_level is not None:
        add_text_element(entry, _q(ns, "fairValLevel"), row.fair_value_level)


def build_nport_xml(doc: FormNPortDocument) -> HandlerOutput:
    """Serialize a FormNPortDocument into the canonical XML envelope."""
    ET.register_namespace("", NPORT_NAMESPACE)
    ET.register_namespace("com", _COMMON_NS)
    ns = NPORT_NAMESPACE
    root = root_element(_q(ns, "edgarSubmission"))
    header = child_element(root, _q(ns, "headerData"))
    add_text_element(header, _q(ns, "submissionType"), doc.submission_type)
    if doc.is_confidential is not None:
        add_text_element(header, _q(ns, "isConfidential"), doc.is_confidential)
    filer_info = child_element(header, _q(ns, "filerInfo"))
    if doc.filer_cik is not None:
        filer = child_element(filer_info, _q(ns, "filer"))
        credentials = child_element(filer, _q(ns, "issuerCredentials"))
        add_text_element(credentials, _q(ns, "cik"), doc.filer_cik)
    form_data = child_element(root, _q(ns, "formData"))
    gen_info = child_element(form_data, _q(ns, "genInfo"))
    add_text_element(gen_info, _q(ns, "regName"), doc.registrant_name)
    if doc.registrant_file_number is not None:
        add_text_element(gen_info, _q(ns, "regFileNumber"), doc.registrant_file_number)
    if doc.registrant_cik is not None:
        add_text_element(gen_info, _q(ns, "regCik"), doc.registrant_cik)
    if doc.registrant_lei is not None:
        add_text_element(gen_info, _q(ns, "regLei"), doc.registrant_lei)
    if doc.series_name is not None:
        add_text_element(gen_info, _q(ns, "seriesName"), doc.series_name)
    if doc.series_lei is not None:
        add_text_element(gen_info, _q(ns, "seriesLei"), doc.series_lei)
    if doc.report_period_end is not None:
        add_text_element(gen_info, _q(ns, "repPdEnd"), doc.report_period_end)
    if doc.report_period_date is not None:
        add_text_element(gen_info, _q(ns, "repPdDate"), doc.report_period_date)
    if doc.is_final_filing is not None:
        add_text_element(gen_info, _q(ns, "isFinalFiling"), doc.is_final_filing)
    fund_info = child_element(form_data, _q(ns, "fundInfo"))
    if doc.total_assets is not None:
        add_text_element(fund_info, _q(ns, "totAssets"), doc.total_assets)
    if doc.total_liabilities is not None:
        add_text_element(fund_info, _q(ns, "totLiabs"), doc.total_liabilities)
    if doc.net_assets is not None:
        add_text_element(fund_info, _q(ns, "netAssets"), doc.net_assets)
    schedule = child_element(form_data, _q(ns, "invstOrSecs"))
    for row in doc.investments:
        _add_investment(schedule, row)
    return canonical_xml_output(root)


def render_nport_to_xml(
    raw_bytes: bytes,
    context: HandlerContext | None = None,
) -> HandlerOutput:
    """Render Form N-PORT raw input to canonical XML with pass-through."""
    passthrough = passthrough_sec_xml(raw_bytes, NPORT_XML_SPEC)
    if passthrough is not None:
        return passthrough
    doc = parse_nport_xml(raw_bytes)
    return build_nport_xml(doc)


__all__ = ["build_nport_xml", "render_nport_to_xml"]
