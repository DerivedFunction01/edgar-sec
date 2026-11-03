"""Streaming parser for SEC Form 13F XML documents.

Handles both 13F documents: the ``edgarSubmission`` cover/summary and
the ``informationTable`` holdings table; thousands-era values (pre-2023
periods, spec versions before v1.7) normalize to dollars.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from edgar_sec.domain.forms.families.form_13f.models import (
    Form13FDocument,
    InfoTableRow,
    ManagerAddress,
)
from edgar_sec.engine.forms.common.extraction import (
    find_child_element,
    local_name,
    xml_element_text,
)

_DOLLARS_ERA_START = (2023, 1, 1)


def _text(elem: ET.Element | None) -> str | None:
    return xml_element_text(elem) or None


def _int(elem: ET.Element | None) -> int | None:
    txt = _text(elem)
    if not txt:
        return None
    try:
        return int(txt.replace(",", ""))
    except ValueError:
        return None


def _bool(elem: ET.Element | None) -> bool | None:
    txt = _text(elem)
    if txt is None:
        return None
    return txt.lower() == "true"


def _find_all(parent: ET.Element, tag_name: str) -> list[ET.Element]:
    return [child for child in parent if local_name(child.tag) == tag_name]


def _period_tuple(period: str | None) -> tuple[int, int, int] | None:
    """Parse an MM-DD-YYYY report period into a comparable tuple."""
    if not period:
        return None
    parts = period.replace("/", "-").split("-")
    if len(parts) != 3:
        return None
    try:
        month, day, year = (int(part) for part in parts)
    except ValueError:
        return None
    if year < 100:
        return None
    return (year, month, day)


def _value_scale(period: str | None) -> int:
    """Dollar multiplier for stated values: 1000 before the v1.7 era."""
    parsed = _period_tuple(period)
    if parsed is not None and parsed < _DOLLARS_ERA_START:
        return 1000
    return 1


def _parse_address(addr_elem: ET.Element | None) -> ManagerAddress | None:
    if addr_elem is None:
        return None
    return ManagerAddress(
        _text(find_child_element(addr_elem, "street1")) or "",
        _text(find_child_element(addr_elem, "street2")),
        _text(find_child_element(addr_elem, "city")) or "",
        _text(find_child_element(addr_elem, "stateOrCountry")) or "",
        _text(find_child_element(addr_elem, "zipCode")),
    )


def _parse_info_table_row(row_elem: ET.Element, scale: int) -> InfoTableRow:
    shares_elem = find_child_element(row_elem, "shrsOrPrnAmt")
    voting_elem = find_child_element(row_elem, "votingAuthority")
    value = _int(find_child_element(row_elem, "value"))
    return InfoTableRow(
        name_of_issuer=_text(find_child_element(row_elem, "nameOfIssuer")) or "",
        title_of_class=_text(find_child_element(row_elem, "titleOfClass")) or "",
        cusip=_text(find_child_element(row_elem, "cusip")) or "",
        value=value * scale if value is not None else None,
        shares_or_principal=(
            _int(find_child_element(shares_elem, "sshPrnamt"))
            if shares_elem is not None
            else None
        ),
        amount_type=(
            _text(find_child_element(shares_elem, "sshPrnamtType"))
            if shares_elem is not None
            else None
        ),
        investment_discretion=_text(
            find_child_element(row_elem, "investmentDiscretion")
        ),
        voting_sole=(
            _int(find_child_element(voting_elem, "Sole"))
            if voting_elem is not None
            else None
        ),
        voting_shared=(
            _int(find_child_element(voting_elem, "Shared"))
            if voting_elem is not None
            else None
        ),
        voting_none=(
            _int(find_child_element(voting_elem, "None"))
            if voting_elem is not None
            else None
        ),
        figi=_text(find_child_element(row_elem, "figi")),
        put_call=_text(find_child_element(row_elem, "putCall")),
        other_managers=_text(find_child_element(row_elem, "otherManager")),
    )


def parse_form_13f_xml(
    raw_bytes: bytes, *, normalize_values: bool = True
) -> Form13FDocument:
    """Parse raw Form 13F XML bytes into the typed domain model.

    ``normalize_values`` applies thousands-to-dollars era scaling;
    canonical renders already carry dollars, so re-parsing passes False.
    """
    root = ET.fromstring(raw_bytes)
    if local_name(root.tag) == "informationTable":
        rows = tuple(
            _parse_info_table_row(row, 1) for row in _find_all(root, "infoTable")
        )
        return Form13FDocument(submission_type="", manager_name="", holdings=rows)

    header = find_child_element(root, "headerData")
    filer_info = find_child_element(header, "filerInfo") if header is not None else None
    period = None
    if filer_info is not None:
        period = _text(find_child_element(filer_info, "periodOfReport"))
    scale = _value_scale(period) if normalize_values else 1
    form_data = find_child_element(root, "formData")
    cover = (
        find_child_element(form_data, "coverPage") if form_data is not None else None
    )
    summary = (
        find_child_element(form_data, "summaryPage") if form_data is not None else None
    )

    submission_type = ""
    live_test_flag = None
    if header is not None:
        submission_type = _text(find_child_element(header, "submissionType")) or ""
    if filer_info is not None:
        live_test_flag = _text(find_child_element(filer_info, "liveTestFlag"))

    manager_name = ""
    manager_address = None
    amendment_number = None
    amendment_type = None
    is_amendment = False
    report_quarter = None
    report_type = None
    file_number = None
    crd_number = None
    sec_file_number = None
    if cover is not None:
        manager_elem = find_child_element(cover, "filingManager")
        if manager_elem is not None:
            manager_name = _text(find_child_element(manager_elem, "name")) or ""
            manager_address = _parse_address(
                find_child_element(manager_elem, "address")
            )
        amendment_number = _int(find_child_element(cover, "amendmentNo"))
        amend_info = find_child_element(cover, "amendmentInfo")
        if amend_info is not None:
            amendment_type = _text(find_child_element(amend_info, "amendmentType"))
        is_amendment = bool(_bool(find_child_element(cover, "isAmendment")))
        report_quarter = _text(find_child_element(cover, "reportCalendarOrQuarter"))
        report_type = _text(find_child_element(cover, "reportType"))
        file_number = _text(find_child_element(cover, "form13FFileNumber"))
        crd_number = _text(find_child_element(cover, "crdNumber"))
        sec_file_number = _text(find_child_element(cover, "secFileNumber"))

    managers_count = None
    entry_total = None
    table_value_total = None
    confidential = None
    if summary is not None:
        managers_count = _int(find_child_element(summary, "otherIncludedManagersCount"))
        entry_total = _int(find_child_element(summary, "tableEntryTotal"))
        stated_total = _int(find_child_element(summary, "tableValueTotal"))
        table_value_total = stated_total * scale if stated_total is not None else None
        confidential = _bool(find_child_element(summary, "isConfidentialOmitted"))

    holdings: tuple[InfoTableRow, ...] = ()
    if form_data is not None:
        for elem in form_data.iter():
            if local_name(elem.tag) == "informationTable":
                holdings = tuple(
                    _parse_info_table_row(row, scale)
                    for row in _find_all(elem, "infoTable")
                )
                break

    return Form13FDocument(
        submission_type=submission_type,
        manager_name=manager_name,
        holdings=holdings,
        live_test_flag=live_test_flag,
        period_of_report=period,
        report_calendar_or_quarter=report_quarter,
        is_amendment=is_amendment,
        amendment_number=amendment_number,
        amendment_type=amendment_type,
        report_type=report_type,
        form13f_file_number=file_number,
        crd_number=crd_number,
        sec_file_number=sec_file_number,
        manager_address=manager_address,
        other_included_managers_count=managers_count,
        table_entry_total=entry_total,
        table_value_total=table_value_total,
        is_confidential_omitted=confidential,
    )


__all__ = ["parse_form_13f_xml"]
