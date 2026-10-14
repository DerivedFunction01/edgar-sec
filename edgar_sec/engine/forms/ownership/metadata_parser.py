"""Metadata extraction for Form 4 filing header, Boxes 1 to 7, and signatures."""

from __future__ import annotations

from dataclasses import dataclass
import re

from edgar_sec.domain.forms.common.checkmarks import (
    CHECKED_TOKENS,
    CHECKMARK_MARK_RE,
)
from edgar_sec.domain.forms.common.vocabulary import SIGNATURE_TITLE_TERMS
from edgar_sec.domain.taxonomy.jurisdictions import STATE_POSTAL_CODES
from edgar_sec.engine.forms.ownership.sections import ClassifiedSection
from edgar_sec.foundation.regex.builder import build_alternation

_STATE_ALT = build_alternation(sorted(STATE_POSTAL_CODES))
_STATE_ZIP_RE = re.compile(rf"\b({_STATE_ALT})\s+(\d{{5}}(?:-\d{{4}})?)\b")
_IRS_RE = re.compile(r"\b(\d{2}-\d{7}|\d{9})\b")
_SIG_DATE_RE = re.compile(r"\b(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b")
_ROLE_TARGETS = (
    ("director", "director"),
    ("officer", "officer"),
    ("ten_percent", "10%"),
    ("other", "other"),
)


@dataclass(frozen=True, slots=True)
class ReportingOwner:
    name: str | None = None
    street: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    is_director: bool = False
    is_officer: bool = False
    is_ten_percent_owner: bool = False
    is_other: bool = False
    officer_title: str | None = None


@dataclass(frozen=True, slots=True)
class Issuer:
    name: str | None = None
    trading_symbol: str | None = None
    irs_number: str | None = None


@dataclass(frozen=True, slots=True)
class FilingPeriod:
    period_of_report: str | None = None
    is_amendment: bool = False
    date_of_original: str | None = None


@dataclass(frozen=True, slots=True)
class Form4Metadata:
    issuer: Issuer
    reporting_owner: ReportingOwner
    period: FilingPeriod
    signature_name: str | None = None
    signature_date: str | None = None


_TEMPLATE_LABELS = ("Last", "First", "Middle", "Street", "City", "State", "Zip")
_TEMPLATE_LABEL_ALT = build_alternation(_TEMPLATE_LABELS, auto_escape=True)
_CLEAN_TEMPLATE_RE = re.compile(rf"\((?:{_TEMPLATE_LABEL_ALT})\)", re.IGNORECASE)
_CITY_MATCH_RE = re.compile(r"(?:[,\n]|^)\s*([A-Za-z\s\.\-]+),?\s*$")
_NAME_MATCH_RE = re.compile(r"Reporting Person\*?\s*(.+?)(?:\(Last\)|\n|$)")
_STREET_MATCH_RE = re.compile(r"(?:\(Middle\)\s*|\n)(.+?)(?:\(Street\)|\n)")
_TITLE_MATCH_RE = re.compile(r"Description\s*([^\n]+)", re.IGNORECASE)
_PERIOD_MATCH_RE = re.compile(
    r"Statement for(?:\s*\(Month/Year\))?\s*:?\s*([A-Za-z0-9/,\- ]+)",
    re.IGNORECASE,
)
_AMEND_MATCH_RE = re.compile(r"Date of Original[^\n]*\n([^\n]+)", re.IGNORECASE)
_SIG_NAME_TERMINATOR_ALT = build_alternation(
    [r"\s+\d{1,2}[-/]\d{1,2}[-/]\d{2,4}", r"\n", r"$"],
    auto_escape=False,
)
_SIG_NAME_RE = re.compile(
    rf"Signature of Reporting Person(?:\s+Date)?\s+([A-Za-z\.\- ]+?)(?:{_SIG_NAME_TERMINATOR_ALT})",
    re.IGNORECASE,
)
_TICKER_KEYWORD_ALT = build_alternation(
    ["trading symbol", "ticker symbol", "symbol"],
    auto_escape=True,
)
_TICKER_LINE_RE = re.compile(
    rf"(?:{_TICKER_KEYWORD_ALT})\s*:?\s*(.+)$",
    re.IGNORECASE,
)


def _clean_template_artifacts(text: str) -> str:
    return _CLEAN_TEMPLATE_RE.sub("\n", text).strip()


def _resolve_checked_roles(role_cell_text: str) -> dict[str, bool]:
    solved: dict[str, bool] = {key: False for key, _ in _ROLE_TARGETS}
    for line in role_cell_text.splitlines():
        line_l = line.lower()
        marks: list[re.Match[str]] = []
        for mark_match in CHECKMARK_MARK_RE.finditer(line):
            tok = mark_match.group(0).strip()
            if tok.upper() == "X" or tok in CHECKED_TOKENS:
                marks.append(mark_match)
        if not marks:
            continue
        role_spans: list[tuple[str, int, int]] = []
        for key, phrase in _ROLE_TARGETS:
            idx = line_l.find(phrase)
            if idx != -1:
                role_spans.append((key, idx, idx + len(phrase)))
        for mark in marks:
            best_key: str | None = None
            min_dist = float("inf")
            for key, start, end in role_spans:
                dist = (
                    start - mark.end()
                    if mark.start() <= start
                    else mark.start() - end + 5
                )
                if dist < min_dist:
                    min_dist = dist
                    best_key = key
            if best_key and min_dist <= 20:
                solved[best_key] = True
    return solved


def _parse_reporting_owner(cell_text: str, role_cell_text: str) -> ReportingOwner:
    name: str | None = None
    street: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None

    cleaned_cell = _clean_template_artifacts(cell_text)
    lines = [line.strip() for line in cleaned_cell.splitlines() if line.strip()]

    for idx, line in enumerate(lines):
        sz = _STATE_ZIP_RE.search(line)
        if sz:
            state = sz.group(1)
            zip_code = sz.group(2)
            city_cand = line[: sz.start()].strip(", \n\r")
            if city_cand:
                city = city_cand
            if idx > 0 and street is None:
                street = lines[idx - 1]
        elif "reporting person" in line.lower():
            m = _NAME_MATCH_RE.search(line)
            if m and m.group(1).strip():
                name = m.group(1).strip(", \n\r")
            elif idx + 1 < len(lines):
                name = lines[idx + 1]

    roles = _resolve_checked_roles(role_cell_text)
    title_match = _TITLE_MATCH_RE.search(role_cell_text)
    officer_title = title_match.group(1).strip() if title_match else None

    return ReportingOwner(
        name=name,
        street=street,
        city=city,
        state=state,
        zip_code=zip_code,
        is_director=roles["director"],
        is_officer=roles["officer"],
        is_ten_percent_owner=roles["ten_percent"],
        is_other=roles["other"],
        officer_title=officer_title,
    )


def _parse_issuer(cell_text: str) -> Issuer:
    lines = [line.strip() for line in cell_text.splitlines() if line.strip()]
    issuer_line = ""
    for idx, line in enumerate(lines):
        if "trading symbol" in line.lower() or "ticker" in line.lower():
            m = _TICKER_LINE_RE.search(line)
            if m and m.group(1).strip():
                issuer_line = m.group(1).strip()
                break
            elif idx + 1 < len(lines):
                issuer_line = lines[idx + 1]
                break

    name: str | None = None
    ticker: str | None = None
    if issuer_line:
        parts = issuer_line.rsplit(" ", 1)
        name = parts[0].strip()
        ticker = parts[1].strip() if len(parts) > 1 else None

    irs_match = _IRS_RE.search(cell_text)
    irs_number = irs_match.group(1) if irs_match else None

    return Issuer(
        name=name,
        trading_symbol=ticker,
        irs_number=irs_number,
    )


def _parse_period(cell_text: str) -> FilingPeriod:
    period_match = _PERIOD_MATCH_RE.search(cell_text)
    period = period_match.group(1).strip() if period_match else None

    amend_match = _AMEND_MATCH_RE.search(cell_text)
    amend_date = amend_match.group(1).strip() if amend_match else None
    is_amendment = bool(amend_date and re.search(r"\d", amend_date))

    return FilingPeriod(
        period_of_report=period,
        is_amendment=is_amendment,
        date_of_original=amend_date if is_amendment else None,
    )


def parse_metadata(
    boxes_section: ClassifiedSection | None,
    signatures_section: ClassifiedSection | None,
) -> Form4Metadata:
    """Extract structured Box 1-7 metadata and signature records."""
    if boxes_section is None:
        return Form4Metadata(
            issuer=Issuer(),
            reporting_owner=ReportingOwner(),
            period=FilingPeriod(),
        )

    cells = [c for r in boxes_section.resolved_grid.rows for c in r if c.strip()]
    owner_cell = next((c for c in cells if "reporting person" in c.lower()), "")
    issuer_cell = next((c for c in cells if "issuer name" in c.lower()), "")
    period_cell = next((c for c in cells if "statement for" in c.lower()), "")
    role_cell = next((c for c in cells if "relationship" in c.lower()), "")

    owner = _parse_reporting_owner(owner_cell, role_cell)
    issuer = _parse_issuer(issuer_cell)
    period = _parse_period(period_cell)

    sig_name: str | None = None
    sig_date: str | None = None
    if signatures_section is not None:
        sig_cells = [
            c for r in signatures_section.resolved_grid.rows for c in r if c.strip()
        ]
        sig_text = " ".join(sig_cells)
        date_match = _SIG_DATE_RE.search(sig_text)
        if date_match:
            sig_date = date_match.group(1)
        name_match = _SIG_NAME_RE.search(sig_text)
        if name_match:
            sig_name = name_match.group(1).strip()

    return Form4Metadata(
        issuer=issuer,
        reporting_owner=owner,
        period=period,
        signature_name=sig_name,
        signature_date=sig_date,
    )


__all__ = [
    "FilingPeriod",
    "Form4Metadata",
    "Issuer",
    "ReportingOwner",
    "parse_metadata",
]
