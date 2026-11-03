"""Parser for pre-2013-05-20 Form 13F plain-text filings.

The text era carries cover page, summary page, and the fixed-column
information table in one body; table column spans come from the
dash-rule line, and stated values (thousands) normalize to dollars.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from edgar_sec.domain.forms.families.form_13f.models import (
    Form13FDocument,
    InfoTableRow,
    ManagerAddress,
)
from edgar_sec.engine.forms.common.entities import is_valid_cusip, parse_cusip

_VALUE_SCALE = 1000
_DASH_RUN = re.compile(r"-{2,}")
_NUMBER = re.compile(r"^[\d,]+(?:\.\d+)?$")
_DOCUMENT_RE = re.compile(
    r"<DOCUMENT>\s*<TYPE>([^<\n]+)(.*?)(?:</DOCUMENT>|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_TEXT_RE = re.compile(r"<TEXT>(.*)", re.IGNORECASE | re.DOTALL)
_ADDRESS_RE = re.compile(r"Address:\s*(.+)\n\s*(.+)", re.IGNORECASE)
_CITY_STATE_RE = re.compile(r"(.+?)[,\s]+([A-Z]{2})\s+(\d{5}(?:-\d{4})?)?$")
_RESTATEMENT_RE = re.compile(r"\[\s*X\s*\]\s*is a restatement", re.IGNORECASE)
_NEW_HOLDINGS_RE = re.compile(r"\[\s*X\s*\]\s*adds new holdings", re.IGNORECASE)
_AMENDMENT_RE = re.compile(
    r"(?:Check here if Amendment\s*\[\s*X\s*\]"
    r"|If Amended report check here:\s*\|\s*X\s*\|)",
    re.IGNORECASE,
)
_PERIOD_RE = re.compile(
    r"Report for the (?:Calendar Year or )?Quarter Ended:?\s*(.+)", re.IGNORECASE
)
_CAPTION_RES = (
    re.compile(r"^\(Name and Address of Institutional Investment Manager"),
    re.compile(r"^Name of Institutional Investment Manager\s*$"),
)
_TABLE_START_RE = re.compile(r"COLUMN 1", re.IGNORECASE)
_MANAGER_NAME_RE = re.compile(
    r"Institutional Investment Manager Filing this Report:\s*\n\s*Name:\s*(.+)",
    re.IGNORECASE,
)
_NAME_LINE_RE = re.compile(r"^\s*Name:\s*(.+)", re.IGNORECASE | re.MULTILINE)
_FILE_NUMBER_RE = re.compile(r"Form 13F File Number:\s*([0-9]+-[0-9]+)", re.IGNORECASE)
_AMENDMENT_NUMBER_RE = re.compile(r"Amendment Number:\s*(\d+)", re.IGNORECASE)
_MANAGERS_COUNT_RE = re.compile(
    r"Number of Other Included Managers:\s*_*\s*([\d,]+)", re.IGNORECASE
)
_ENTRY_TOTAL_RE = re.compile(
    r"Information Table Entry Total:\s*_*\s*([\d,]+)", re.IGNORECASE
)
_VALUE_TOTAL_RE = re.compile(
    r"Information Table Value Total:[_\s]*\$?[_\s]*([\d,]+)", re.IGNORECASE
)
_CHECKED = r"(?:\[\s*X\s*\]|\(\s*X\s*\)|\|\s*X\s*\|)\s*"
_REPORT_TYPE_RES = tuple(
    (name, re.compile(_CHECKED + re.escape(name), re.IGNORECASE))
    for name in ("13F HOLDINGS REPORT", "13F NOTICE", "13F COMBINATION REPORT")
)


@dataclass(frozen=True, slots=True)
class _CoverFields:
    """Cover and summary values extracted from a text-era filing."""

    manager_name: str = ""
    address: ManagerAddress | None = None
    period: str | None = None
    file_number: str | None = None
    report_type: str | None = None
    is_amendment: bool = False
    amendment_number: int | None = None
    amendment_type: str | None = None
    managers_count: int | None = None
    entry_total: int | None = None
    value_total: int | None = None


def _clean(text: str) -> str:
    return text.strip().strip("_").strip()


def _search(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    if match is None:
        return None
    return _clean(match.group(1)) or None


def _to_int(text: str | None) -> int | None:
    if not text:
        return None
    try:
        return int(float(text.replace(",", "").replace("$", "")))
    except ValueError:
        return None


def _filing_text(raw_bytes: bytes) -> tuple[str, str]:
    """Return (document text, submission type) unwrapping SEC envelopes."""
    text = raw_bytes.decode("utf-8", errors="replace")
    submission_type = ""
    doc_match = _DOCUMENT_RE.search(text)
    if doc_match is not None and doc_match.group(1).strip().upper().startswith("13F"):
        submission_type = doc_match.group(1).strip().upper()
        body = doc_match.group(2)
        text_match = _TEXT_RE.search(body)
        if text_match is not None:
            text = text_match.group(1)
    return text, submission_type


def _manager_from_caption(lines: list[str]) -> str | None:
    """Old covers put the manager name above its caption line."""
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not any(pattern.match(stripped) for pattern in _CAPTION_RES):
            continue
        above: list[str] = []
        cursor = index - 1
        while cursor >= 0 and len(above) < 2:
            candidate = lines[cursor].strip()
            cursor -= 1
            if not candidate or set(candidate) <= {"-", "_", "="}:
                continue
            above.append(candidate)
        if not above:
            return None
        if len(above) == 2 and "," in above[0] and any(ch.isdigit() for ch in above[0]):
            return _clean(above[1])
        return _clean(above[0])
    return None


def _parse_cover(text: str) -> _CoverFields:
    period = _search(_PERIOD_RE, text)
    manager_name = (
        _search(_MANAGER_NAME_RE, text)
        or _search(_NAME_LINE_RE, text)
        or _manager_from_caption(text.splitlines())
    )
    table_start = _TABLE_START_RE.search(text)
    summary_scope = text[: table_start.start()] if table_start else text
    address = None
    address_match = _ADDRESS_RE.search(text)
    if address_match is not None:
        street = _clean(address_match.group(1))
        city_line = _clean(address_match.group(2))
        city_state = _CITY_STATE_RE.match(city_line)
        if city_state is not None:
            address = ManagerAddress(
                street,
                None,
                city_state.group(1).strip(),
                city_state.group(2),
                city_state.group(3),
            )
    report_type = None
    for candidate, pattern in _REPORT_TYPE_RES:
        if pattern.search(text):
            report_type = candidate
            break
    amendment_type = None
    if _RESTATEMENT_RE.search(text):
        amendment_type = "RESTATEMENT"
    elif _NEW_HOLDINGS_RE.search(text):
        amendment_type = "NEW HOLDINGS"
    stated_total = _to_int(_search(_VALUE_TOTAL_RE, summary_scope))
    return _CoverFields(
        manager_name=manager_name or "",
        address=address,
        period=period,
        file_number=_search(_FILE_NUMBER_RE, text),
        report_type=report_type,
        is_amendment=bool(_AMENDMENT_RE.search(text)),
        amendment_number=_to_int(_search(_AMENDMENT_NUMBER_RE, text)),
        amendment_type=amendment_type,
        managers_count=_to_int(_search(_MANAGERS_COUNT_RE, summary_scope)),
        entry_total=_to_int(_search(_ENTRY_TOTAL_RE, summary_scope)),
        value_total=stated_total * _VALUE_SCALE if stated_total is not None else None,
    )


def _dash_spans(line: str) -> list[tuple[int, int]] | None:
    spans = [(m.start(), m.end()) for m in _DASH_RUN.finditer(line)]
    if len(spans) < 8:
        return None
    return spans


def _zone(line: str, spans: list[tuple[int, int]], index: int) -> str:
    start = spans[index][0]
    if index + 1 < len(spans):
        end = spans[index + 1][0]
    else:
        end = spans[index][1] + 14
    return line[start:end] if len(line) > start else ""


def _parse_table_row(line: str, spans: list[tuple[int, int]]) -> InfoTableRow | None:
    cusip_text = _zone(line, spans, 2).strip()
    cusip = parse_cusip(cusip_text) if cusip_text else None
    if cusip is None or not is_valid_cusip(cusip):
        return None
    value = _to_int(_zone(line, spans, 3).strip())
    shares = None
    amount_type = None
    put_call = None
    if len(spans) >= 11:
        # Fine-grained rule: every sub-column has its own dash run; the
        # other-managers run (index 8) exists only in the 12-run form.
        shares = _to_int(_zone(line, spans, 4).strip())
        type_token = _zone(line, spans, 5).strip().upper()
        if type_token in ("SH", "PRN"):
            amount_type = type_token
        put_token = _zone(line, spans, 6).strip().upper()
        if put_token in ("PUT", "CALL"):
            put_call = put_token.capitalize()
        discretion = _clean(_zone(line, spans, 7)) or None
        other_managers = (
            _clean(_zone(line, spans, 8)) or None if len(spans) >= 12 else None
        )
        voting_sole = _to_int(_zone(line, spans, len(spans) - 3).strip())
        voting_shared = _to_int(_zone(line, spans, len(spans) - 2).strip())
        voting_none = _to_int(_zone(line, spans, len(spans) - 1).strip())
    else:
        for token in _zone(line, spans, 4).split():
            upper = token.upper()
            if shares is None and _NUMBER.match(token):
                shares = _to_int(token)
            elif upper in ("SH", "PRN"):
                amount_type = upper
            elif upper in ("PUT", "CALL"):
                put_call = upper.capitalize()
        votes = [
            _to_int(token)
            for token in _zone(line, spans, 7).split()
            if _NUMBER.match(token)
        ]
        discretion = _clean(_zone(line, spans, 5)) or None
        other_managers = _clean(_zone(line, spans, 6)) or None
        voting_sole = votes[0] if len(votes) > 0 else None
        voting_shared = votes[1] if len(votes) > 1 else None
        voting_none = votes[2] if len(votes) > 2 else None
    if discretion is not None and discretion.upper() in _MISALIGNED_DISCRETION:
        return None
    if value is not None and value < 0:
        return None
    return InfoTableRow(
        name_of_issuer=_clean(_zone(line, spans, 0)),
        title_of_class=_clean(_zone(line, spans, 1)),
        cusip=cusip,
        value=value * _VALUE_SCALE if value is not None else None,
        shares_or_principal=shares,
        amount_type=amount_type,
        investment_discretion=discretion,
        voting_sole=voting_sole,
        voting_shared=voting_shared,
        voting_none=voting_none,
        put_call=put_call,
        other_managers=other_managers,
    )


def _parse_holdings(lines: list[str]) -> tuple[InfoTableRow, ...]:
    rows: list[InfoTableRow] = []
    spans = None
    for line in lines:
        refreshed = _dash_spans(line)
        if refreshed is not None:
            spans = refreshed
            continue
        if spans is None:
            continue
        row = _parse_table_row(line, spans)
        if row is not None:
            rows.append(row)
    if not rows:
        return _parse_holdings_vertical(lines)
    return tuple(rows)


_DISCRETION_TOKENS = ("SOLE", "DFND", "OTR")
_MISALIGNED_DISCRETION = ("SH", "PRN", "PUT", "CALL")


def _vertical_row(lines: list[str], cusip_index: int) -> InfoTableRow | None:
    """Assemble one row around a bare-CUSIP line in a vertical table."""
    cusip = parse_cusip(lines[cusip_index].strip())
    if cusip is None or not is_valid_cusip(cusip):
        return None
    above: list[str] = []
    cursor = cusip_index - 1
    while cursor >= 0 and len(above) < 2:
        candidate = lines[cursor].strip()
        cursor -= 1
        if candidate:
            above.append(candidate)
    if len(above) < 2:
        return None
    title_of_class, name_of_issuer = above[0], above[1]
    numbers: list[int | None] = []
    amount_type = None
    put_call = None
    discretion = None
    cursor = cusip_index + 1
    while cursor < len(lines) and len(numbers) < 5:
        token = lines[cursor].strip()
        cursor += 1
        if not token:
            continue
        upper = token.upper()
        if _NUMBER.match(token):
            numbers.append(_to_int(token))
        elif upper in ("SH", "PRN"):
            amount_type = upper
        elif upper in ("PUT", "CALL"):
            put_call = upper.capitalize()
        elif upper in _DISCRETION_TOKENS or upper in ("S", "D", "O"):
            discretion = upper
        else:
            break
    if len(numbers) < 2:
        return None
    votes = numbers[2:]
    return InfoTableRow(
        name_of_issuer=_clean(name_of_issuer),
        title_of_class=_clean(title_of_class),
        cusip=cusip,
        value=numbers[0] * _VALUE_SCALE if numbers[0] is not None else None,
        shares_or_principal=numbers[1],
        amount_type=amount_type,
        investment_discretion=discretion,
        voting_sole=votes[0] if len(votes) > 0 else None,
        voting_shared=votes[1] if len(votes) > 1 else None,
        voting_none=votes[2] if len(votes) > 2 else None,
        put_call=put_call,
    )


def _parse_holdings_vertical(lines: list[str]) -> tuple[InfoTableRow, ...]:
    rows: list[InfoTableRow] = []
    for index, line in enumerate(lines):
        token = line.strip()
        if len(token) != 9:
            continue
        row = _vertical_row(lines, index)
        if row is not None:
            rows.append(row)
    return tuple(rows)


def parse_form_13f_text(raw_bytes: bytes) -> Form13FDocument:
    """Parse a pre-2013 Form 13F text filing into the domain model."""
    text, submission_type = _filing_text(raw_bytes)
    cover = _parse_cover(text)
    holdings = _parse_holdings(text.splitlines())
    return Form13FDocument(
        submission_type=submission_type,
        manager_name=cover.manager_name,
        holdings=holdings,
        period_of_report=cover.period,
        report_calendar_or_quarter=cover.period,
        is_amendment=cover.is_amendment,
        amendment_number=cover.amendment_number,
        amendment_type=cover.amendment_type,
        report_type=cover.report_type,
        form13f_file_number=cover.file_number,
        manager_address=cover.address,
        other_included_managers_count=cover.managers_count,
        table_entry_total=cover.entry_total,
        table_value_total=cover.value_total,
    )


__all__ = ["parse_form_13f_text"]
