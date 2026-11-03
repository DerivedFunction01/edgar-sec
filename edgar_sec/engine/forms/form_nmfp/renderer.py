"""Canonical XML renderer for SEC Form N-MFP filings."""

from __future__ import annotations

from typing import TYPE_CHECKING
import xml.etree.ElementTree as ET

from edgar_sec.domain.forms.families.form_nmfp.models import (
    FormNMfpDocument,
    NMfpSecurity,
)
from edgar_sec.domain.forms.families.form_nmfp.taxonomy import (
    N_MFP3_NAMESPACE,
    N_MFP_XML_SPEC,
)
from edgar_sec.engine.document_processing.outputs import HandlerOutput
from edgar_sec.engine.forms.common.native_xml import passthrough_sec_xml
from edgar_sec.engine.forms.common.xml_builder import (
    add_text_element,
    canonical_xml_output,
    child_element,
    root_element,
)
from edgar_sec.engine.forms.form_nmfp.xml_parser import parse_nmfp_xml

if TYPE_CHECKING:
    from edgar_sec.engine.document_processing.registry import HandlerContext

_COMMON_NS = "http://www.sec.gov/edgar/common"


def _q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def _add_security(parent: ET.Element, row: NMfpSecurity) -> None:
    ns = N_MFP3_NAMESPACE
    entry = child_element(parent, _q(ns, "scheduleOfPortfolioSecuritiesInfo"))
    add_text_element(entry, _q(ns, "nameOfIssuer"), row.issuer_name)
    add_text_element(entry, _q(ns, "titleOfIssuer"), row.title)
    add_text_element(entry, _q(ns, "CUSIPMember"), row.cusip)
    if row.lei is not None:
        add_text_element(entry, _q(ns, "LEIID"), row.lei)
    if row.isin is not None:
        add_text_element(entry, _q(ns, "ISINId"), row.isin)
    if row.investment_category is not None:
        add_text_element(entry, _q(ns, "investmentCategory"), row.investment_category)
    if row.maturity_date_wam is not None:
        add_text_element(
            entry, _q(ns, "investmentMaturityDateWAM"), row.maturity_date_wam
        )
    if row.maturity_date_wal is not None:
        add_text_element(
            entry, _q(ns, "investmentMaturityDateWAL"), row.maturity_date_wal
        )
    if row.value_including_support is not None:
        add_text_element(
            entry,
            _q(ns, "includingValueOfAnySponsorSupport"),
            row.value_including_support,
        )
    if row.percent_of_net_assets is not None:
        add_text_element(
            entry,
            _q(ns, "percentageOfMoneyMarketFundNetAssets"),
            row.percent_of_net_assets,
        )
    if row.daily_liquid_asset is not None:
        add_text_element(
            entry, _q(ns, "dailyLiquidAssetSecurityFlag"), row.daily_liquid_asset
        )
    if row.weekly_liquid_asset is not None:
        add_text_element(
            entry, _q(ns, "weeklyLiquidAssetSecurityFlag"), row.weekly_liquid_asset
        )
    if row.illiquid is not None:
        add_text_element(entry, _q(ns, "illiquidSecurityFlag"), row.illiquid)


def build_nmfp_xml(doc: FormNMfpDocument) -> HandlerOutput:
    """Serialize a FormNMfpDocument into the canonical XML envelope."""
    ET.register_namespace("", N_MFP3_NAMESPACE)
    ET.register_namespace("com", _COMMON_NS)
    ns = N_MFP3_NAMESPACE
    root = root_element(_q(ns, "edgarSubmission"))
    header = child_element(root, _q(ns, "headerData"))
    add_text_element(header, _q(ns, "submissionType"), doc.submission_type)
    form_data = child_element(root, _q(ns, "formData"))
    general = child_element(form_data, _q(ns, "generalInfo"))
    if doc.report_date is not None:
        add_text_element(general, _q(ns, "reportDate"), doc.report_date)
    if doc.registrant_name is not None:
        add_text_element(general, _q(ns, "registrantFullName"), doc.registrant_name)
    if doc.registrant_cik is not None:
        add_text_element(general, _q(ns, "cik"), doc.registrant_cik)
    if doc.series_name is not None:
        add_text_element(general, _q(ns, "nameOfSeries"), doc.series_name)
    if doc.series_lei is not None:
        add_text_element(general, _q(ns, "leiOfSeries"), doc.series_lei)
    if doc.series_id is not None:
        add_text_element(general, _q(ns, "seriesId"), doc.series_id)
    for row in doc.securities:
        _add_security(form_data, row)
    return canonical_xml_output(root)


def render_nmfp_to_xml(
    raw_bytes: bytes,
    context: HandlerContext | None = None,
) -> HandlerOutput:
    """Render Form N-MFP raw input to canonical XML with pass-through."""
    passthrough = passthrough_sec_xml(raw_bytes, N_MFP_XML_SPEC)
    if passthrough is not None:
        return passthrough
    doc = parse_nmfp_xml(raw_bytes)
    return build_nmfp_xml(doc)


__all__ = ["build_nmfp_xml", "render_nmfp_to_xml"]
