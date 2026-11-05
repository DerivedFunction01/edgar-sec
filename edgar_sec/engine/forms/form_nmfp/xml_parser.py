"""Parser for SEC Form N-MFP XML documents across schema generations."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from edgar_sec.domain.forms.families.form_nmfp.models import (
    FormNMfpDocument,
    NMfpSecurity,
)
from edgar_sec.domain.forms.families.form_nmfp.taxonomy import (
    N_MFP_GENERATION_BY_NAMESPACE,
)
from edgar_sec.engine.forms.common.extraction import (
    find_child_element,
    find_child_elements,
    xml_element_text_or_none,
)


def _namespace_of(root: ET.Element) -> str:
    tag = root.tag
    if tag.startswith("{"):
        return tag[1:].partition("}")[0]
    return ""


def _parse_security(row_elem: ET.Element) -> NMfpSecurity:
    cusip = find_child_element(row_elem, "CUSIPMember")
    if cusip is None:
        cusip = find_child_element(row_elem, "cusipNumber")
    return NMfpSecurity(
        issuer_name=xml_element_text_or_none(
            find_child_element(row_elem, "nameOfIssuer")
        )
        or "",
        title=xml_element_text_or_none(find_child_element(row_elem, "titleOfIssuer"))
        or "",
        cusip=xml_element_text_or_none(cusip) or "",
        lei=xml_element_text_or_none(find_child_element(row_elem, "LEIID")),
        isin=xml_element_text_or_none(find_child_element(row_elem, "ISINId")),
        investment_category=xml_element_text_or_none(
            find_child_element(row_elem, "investmentCategory")
        ),
        maturity_date_wam=xml_element_text_or_none(
            find_child_element(row_elem, "investmentMaturityDateWAM")
        ),
        maturity_date_wal=xml_element_text_or_none(
            find_child_element(row_elem, "investmentMaturityDateWAL")
        ),
        value_including_support=xml_element_text_or_none(
            find_child_element(row_elem, "includingValueOfAnySponsorSupport")
        ),
        percent_of_net_assets=xml_element_text_or_none(
            find_child_element(row_elem, "percentageOfMoneyMarketFundNetAssets")
        ),
        daily_liquid_asset=xml_element_text_or_none(
            find_child_element(row_elem, "dailyLiquidAssetSecurityFlag")
        ),
        weekly_liquid_asset=xml_element_text_or_none(
            find_child_element(row_elem, "weeklyLiquidAssetSecurityFlag")
        ),
        illiquid=xml_element_text_or_none(
            find_child_element(row_elem, "illiquidSecurityFlag")
        ),
    )


def parse_nmfp_xml(raw_bytes: bytes) -> FormNMfpDocument:
    """Parse raw Form N-MFP XML bytes into the typed domain model.

    Generations 2 and 3 parse fully; generation 1 yields its header
    identity only, its body riding native pass-through.
    """
    root = ET.fromstring(raw_bytes)
    generation = N_MFP_GENERATION_BY_NAMESPACE.get(_namespace_of(root))
    header = find_child_element(root, "headerData")
    form_data = find_child_element(root, "formData")
    general = (
        find_child_element(form_data, "generalInfo") if form_data is not None else None
    )
    securities: tuple[NMfpSecurity, ...] = ()
    if generation in (2, 3) and form_data is not None:
        securities = tuple(
            _parse_security(row)
            for row in find_child_elements(
                form_data, "scheduleOfPortfolioSecuritiesInfo"
            )
        )
    classes = (
        len(find_child_elements(form_data, "classLevelInfo"))
        if form_data is not None
        else 0
    )
    series_name = xml_element_text_or_none(find_child_element(general, "nameOfSeries"))
    if series_name is None:
        series_name = xml_element_text_or_none(
            find_child_element(general, "seriesName")
        )
    if generation == 1:
        # Generation 1 files a flat header directly under the root.
        return FormNMfpDocument(
            submission_type=xml_element_text_or_none(
                find_child_element(root, "submissionType")
            )
            or "",
            securities=(),
            generation=1,
            report_date=xml_element_text_or_none(
                find_child_element(root, "DocumentPeriodEndDate")
            ),
            registrant_cik=xml_element_text_or_none(
                find_child_element(root, "EntityCentralIndexKey")
            ),
            series_id=xml_element_text_or_none(find_child_element(root, "seriesId")),
        )
    return FormNMfpDocument(
        submission_type=(
            xml_element_text_or_none(find_child_element(header, "submissionType")) or ""
            if header is not None
            else ""
        ),
        securities=securities,
        generation=generation,
        report_date=(
            xml_element_text_or_none(find_child_element(general, "reportDate"))
            if general is not None
            else None
        ),
        registrant_name=(
            xml_element_text_or_none(find_child_element(general, "registrantFullName"))
            if general is not None
            else None
        ),
        registrant_cik=(
            xml_element_text_or_none(find_child_element(general, "cik"))
            if general is not None
            else None
        ),
        series_name=series_name,
        series_id=(
            xml_element_text_or_none(find_child_element(general, "seriesId"))
            if general is not None
            else None
        ),
        series_lei=(
            xml_element_text_or_none(find_child_element(general, "leiOfSeries"))
            if general is not None
            else None
        ),
        class_count=classes,
    )


__all__ = ["parse_nmfp_xml"]
